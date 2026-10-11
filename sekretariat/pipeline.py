"""Letter processing, run by Cloud Tasks (/internal/process/{id}) with retries.

    received ──OCR──▶ ocr_done ──DLP+mask──▶ masked ──Gemini+guard──▶ verdict
        │                │                      │
        │ too little text│                      │
        ▼                │                      │
    unreadable           └──── any error: raise, Cloud Tasks retries ────┘
                                last attempt: failed (FORWARD to the coordinator)

Each stage saves its result and the new status, so a retry resumes where the
previous attempt stopped, and a duplicate delivery of a finished letter does
nothing. Model refusals and schema errors are not retried: the guard turns them
into FORWARD. Logs and exceptions never carry letter content.

Letter fields written here (besides those set at upload: uploaded_by, pages,
delivery_date, upload_private):
    raw_text, masked_text, segments          OCR and masking (D5)
    verdict, reasons, analysis, escalation_hits
    quote_spans_masked, quote_spans_raw      for highlighting (D5 step 8)
    deadline {date, basis, confirmed}        D10, D8; always unconfirmed here
    addressee, owner, state, private         D18, DR-5
    assigned                                 failed only: e-mail to the owner (D6)
"""

import dataclasses
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sekretariat.blobs import Blobs
from sekretariat.deadlines import compute_deadline
from sekretariat.guard import guard
from sekretariat.household import Member, Role
from sekretariat.llm import LetterAnalysis, LlmFailure, Verdict
from sekretariat.mask import Finding, MaskResult, Segment, mask
from sekretariat.notices import FAILED, assigned
from sekretariat.owners import initial_owner
from sekretariat.rules import Rule
from sekretariat.store import Store, now

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # matches the Cloud Tasks queue
MIN_READABLE_CHARS = 30
FINAL = {"verdict", "failed", "unreadable"}
FAILED_REASON = "ANALYSIS_FAILED"


@dataclass
class Services:
    store: Store
    blobs: Blobs
    ocr: Callable[[list[tuple[bytes, str]]], str]
    inspect: Callable[[str], list[Finding]]
    analyze: Callable[[str, list[Rule]], LetterAnalysis | LlmFailure]
    household: list[Member]
    # Immediate reminder when the deadline is already close (D3); must not raise.
    remind: Callable[[str], None] = lambda letter_id: None
    # E-mail to the owner of a letter that could not be analyzed (D6); must not raise.
    notify: Callable[[str], None] = lambda member_id: None


class RetryableError(Exception):
    pass


def process(services: Services, letter_id: str, attempt: int = 0) -> str:
    """Runs the remaining stages. Returns the final status, or raises to be retried."""
    letter = services.store.get_letter(letter_id)
    if letter is None:
        log.warning("letter %s not found", letter_id)
        return "missing"
    judged = False
    try:
        if letter["status"] == "received":
            letter |= _ocr(services, letter_id, letter)
        if letter["status"] == "ocr_done":
            letter |= _mask(services, letter_id, letter)
        if letter["status"] == "masked":
            letter |= _verdict(services, letter_id, letter)
            judged = True
    except Exception as error:
        if attempt + 1 >= MAX_ATTEMPTS:
            log.error(
                "letter %s failed at %s: %s", letter_id, letter["status"], type(error).__name__
            )
            letter |= _fail(services, letter_id, letter)
            services.notify(letter["owner"])
        else:
            log.warning("letter %s: retry after %s", letter_id, type(error).__name__)
            raise
    if judged:
        services.remind(letter_id)
    return letter["status"]


def _save(services: Services, letter_id: str, fields: dict) -> dict:
    services.store.update_letter(letter_id, fields)
    return fields


def _ocr(services: Services, letter_id: str, letter: dict) -> dict:
    pages = [services.blobs.get(page["path"]) for page in letter["pages"]]
    text = services.ocr(pages)
    if sum(not c.isspace() for c in text) < MIN_READABLE_CHARS:
        return _save(services, letter_id, {"status": "unreadable"})
    return _save(services, letter_id, {"status": "ocr_done", "raw_text": text})


def _mask(services: Services, letter_id: str, letter: dict) -> dict:
    raw_text = letter["raw_text"]
    result = mask(raw_text, services.inspect(raw_text), services.household)
    # Firestore does not allow arrays nested in arrays, so segments are maps.
    segments = [dataclasses.asdict(s) for s in result.segments]
    return _save(
        services,
        letter_id,
        {"status": "masked", "masked_text": result.masked_text, "segments": segments},
    )


def _verdict(services: Services, letter_id: str, letter: dict) -> dict:
    masked_text = letter["masked_text"]
    rules = services.store.rules()
    outcome = services.analyze(masked_text, rules)
    if isinstance(outcome, LlmFailure) and outcome.reason.startswith("error"):
        raise RetryableError(outcome.reason)  # network, quota, timeout

    checked = guard(
        masked_text,
        outcome,
        {rule.id for rule in rules},
        member_count=len(services.household),
        escalation=services.store.escalation(),
    )
    result = MaskResult(masked_text, tuple(Segment(**s) for s in letter["segments"]))
    analysis = checked.analysis
    addressee = _addressee(services.household, analysis.addressee if analysis else None)
    deadline = None
    if analysis is not None:
        computed = compute_deadline(analysis, date.fromisoformat(letter["delivery_date"]))
        if computed is not None:
            deadline = {
                "date": computed.date.isoformat(),
                "basis": computed.basis.value,
                "confirmed": False,
            }

    owner = initial_owner(services.household, analysis.addressee if analysis else None)
    services.store.add_event(letter_id, _event(owner))
    return _save(
        services,
        letter_id,
        {
            "status": "verdict",
            "verdict": checked.verdict.value,
            "reasons": [r.value for r in checked.reasons],
            "analysis": analysis.model_dump(mode="json") if analysis else None,
            "escalation_hits": list(checked.escalation_hits),
            "quote_spans_masked": {k: list(v) for k, v in checked.quote_spans.items()},
            "quote_spans_raw": {k: list(result.to_raw(*v)) for k, v in checked.quote_spans.items()},
            "deadline": deadline,
            "addressee": addressee.id if addressee else None,
            "owner": owner.owner,
            "state": "open",
            "private": _private(letter, addressee),
            "processed_at": now(),
        },
    )


def _fail(services: Services, letter_id: str, letter: dict) -> dict:
    owner = initial_owner(services.household, None)
    services.store.add_event(letter_id, _event(owner))
    return _save(
        services,
        letter_id,
        {
            "status": "failed",
            "verdict": Verdict.FORWARD.value,
            "reasons": [FAILED_REASON],
            "deadline": None,
            "addressee": None,
            "owner": owner.owner,
            "assigned": assigned(owner.owner, None, now(), FAILED),
            "state": "open",
            "private": bool(letter.get("upload_private")),
            "processed_at": now(),
        },
    )


def _addressee(household: list[Member], placeholder: str | None) -> Member | None:
    if placeholder and placeholder.startswith("OSOBA_") and placeholder[6:].isdigit():
        index = int(placeholder[6:]) - 1
        if 0 <= index < len(household):
            return household[index]
    return None


def _private(letter: dict, addressee: Member | None) -> bool:
    """DR-5: letters to an adult member with an account start private to the coordinator."""
    return bool(letter.get("upload_private")) or (
        addressee is not None and addressee.role == Role.DOMOWNIK
    )


def _event(owner) -> dict:
    return {
        "cause": owner.cause.value,
        "owner": owner.owner,
        "previous": owner.previous,
        "actor": owner.actor,
    }
