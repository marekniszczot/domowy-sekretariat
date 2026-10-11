"""Deterministic guard: the model proposes a verdict, code decides whether to trust it.

    LlmFailure ───────────────────────────────────────────▶ FORWARD [MODEL_FAILED]
    LetterAnalysis
      ├─ addressee OSOBA_n outside the household ──────────▶ FORWARD [BAD_ADDRESSEE]
      ├─ any *_quote not found in normalized masked text ─▶ FORWARD [QUOTE_NOT_FOUND]
      ├─ rule_id unknown ──────────────────────────────────▶ FORWARD [UNKNOWN_RULE]
      ├─ rule_id null with NONE or SELF ───────────────────▶ FORWARD [MISSING_RULE]
      ├─ confidence < threshold ───────────────────────────▶ FORWARD [LOW_CONFIDENCE]
      ├─ the letter talks to the system (injection) ───────▶ FORWARD [INJECTION]
      ├─ escalation entry in masked text ──────────────────▶ FORWARD [ESCALATION]
      └─ none of the above ────────────────────────────────▶ model verdict

All checks run, so every reason is reported. ESCALATION means "urgent" in the UI;
the other reasons mean "not sure, forward it".

Quote normalization (same for text and quote): words split by a hyphen at a line
end are joined, whitespace runs become one space, case is folded, typographic
quotes and dashes become ASCII. Each normalized character remembers its position
in the masked text, so a found quote yields an exact masked span for highlighting.

Injection signs: words a letter has no reason to use, because they are ours: the
answer's field names, the prompt's tags, rule ids („reguła R4”), and requests to
ignore instructions. The model is told the same, the guard does not rely on it.

Escalation entries are word prefixes on the normalized masked text, so case and
most Polish inflection are covered: "urz skarbow" matches "Urzędu Skarbowego",
"komorni" matches "komornika" and "komorniczej". Where the stem itself changes,
the list has both ("wypowiedz", "wypowiad"; "wezwani do zapłat", "wzyw do zapłat");
words in an entry are consecutive, so "wzywa Pana do zapłaty" needs its own entry.
A hit inside standard wording that every decision carries does not count (EXEMPT,
same syntax): "odwołanie do Sądu Okręgowego" in a ZUS decision is not a letter
from a court. Another hit of the same entry elsewhere in the letter still counts.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from sekretariat.llm import LetterAnalysis, LlmFailure, Verdict

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
DEFAULT_ESCALATION = (
    "komorni",
    "sąd",
    "egzekuc",
    "wypowiedz",
    "wypowiad",
    "urz skarbow",
    "wezwani do zapłat",
    "wzyw do zapłat",
    "wzyw pan do zapłat",
    "wzyw państw do zapłat",
)
# Boilerplate of decisions and instructions; built in, not editable in „Dom”.
EXEMPT = (
    "odwoł do sąd",
    "odwoł wnos się do sąd",
    "skarg do sąd administracyjn",
    "skarg do wojewódzk sąd administracyjn",
    "postanowieni sąd o nabyci spadk",
)
QUOTE_FIELDS = ("rule_trigger_quote", "deadline_quote", "consequence_quote", "letter_date_quote")

_PUNCTUATION = str.maketrans({"„": '"', "”": '"', "“": '"', "‚": "'", "‘": "'", "’": "'",
                              "–": "-", "—": "-", " ": " "})  # fmt: skip
_LINE_END_HYPHEN = re.compile(r"(?<=\w)-[ \t]*\r?\n\s*(?=\w)")
_OSOBA = re.compile(r"^OSOBA_(\d+)$")
# Matched on the normalized (case-folded) text.
_INJECTION = re.compile(
    r"\b(verdict|rule_id|rule_trigger_quote|deadline_type|sender_type|confidence)\b"
    r"|</?\s*(pismo|regulamin)\s*>"
    r"|\breguł\w*\s+r\d+\b"
    r"|\b(ignore|disregard)\W+(\w+\W+){0,3}instructions"
    r"|\bzignoruj\w*\W+(\w+\W+){0,3}(instrukcj|polece|zasad|regulamin)"
    r"|\bdla\s+(systemu|systemów|modelu|asystenta|sztucznej\s+inteligencji)\b"
)


class Reason(StrEnum):
    MODEL_FAILED = "MODEL_FAILED"
    BAD_ADDRESSEE = "BAD_ADDRESSEE"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    UNKNOWN_RULE = "UNKNOWN_RULE"
    MISSING_RULE = "MISSING_RULE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INJECTION = "INJECTION"
    ESCALATION = "ESCALATION"


@dataclass(frozen=True)
class GuardResult:
    verdict: Verdict
    reasons: tuple[Reason, ...]
    analysis: LetterAnalysis | None
    # Masked-text span of every verified quote, by field name.
    quote_spans: dict[str, tuple[int, int]] = field(default_factory=dict)
    escalation_hits: tuple[str, ...] = ()


def guard(
    masked_text: str,
    outcome: LetterAnalysis | LlmFailure,
    rule_ids: set[str],
    member_count: int,
    escalation: tuple[str, ...] = DEFAULT_ESCALATION,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> GuardResult:
    hits = escalation_hits(masked_text, escalation)
    escalation_reasons = (Reason.ESCALATION,) if hits else ()
    injection_reasons = (Reason.INJECTION,) if injection_signs(masked_text) else ()

    if isinstance(outcome, LlmFailure):
        reasons = (Reason.MODEL_FAILED, *injection_reasons, *escalation_reasons)
        return GuardResult(Verdict.FORWARD, reasons, None, escalation_hits=hits)

    reasons: list[Reason] = []
    osoba = _OSOBA.match(outcome.addressee)
    if osoba and int(osoba.group(1)) > member_count:
        reasons.append(Reason.BAD_ADDRESSEE)

    spans = {}
    for name in QUOTE_FIELDS:
        quote = getattr(outcome, name)
        if quote is None:
            continue
        span = find_quote(masked_text, quote)
        if span is None:
            reasons.append(Reason.QUOTE_NOT_FOUND)
        else:
            spans[name] = span

    if outcome.rule_id is None:
        if outcome.verdict != Verdict.FORWARD:
            reasons.append(Reason.MISSING_RULE)
    elif outcome.rule_id not in rule_ids:
        reasons.append(Reason.UNKNOWN_RULE)

    if outcome.confidence < confidence_threshold:
        reasons.append(Reason.LOW_CONFIDENCE)
    reasons.extend(injection_reasons)
    reasons.extend(escalation_reasons)

    reasons = tuple(dict.fromkeys(reasons))
    verdict = Verdict.FORWARD if reasons else outcome.verdict
    return GuardResult(verdict, reasons, outcome, spans, hits)


def normalize(text: str) -> tuple[str, list[int]]:
    """Normalized text and, for each of its characters, the index in `text`."""
    joined = []
    positions = []
    pos = 0
    for match in _LINE_END_HYPHEN.finditer(text):
        joined.append(text[pos : match.start()])
        positions.extend(range(pos, match.start()))
        pos = match.end()
    joined.append(text[pos:])
    positions.extend(range(pos, len(text)))
    source = "".join(joined)

    out: list[str] = []
    index: list[int] = []
    for char, origin in zip(source, positions, strict=True):
        char = char.translate(_PUNCTUATION)
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(origin)
            continue
        for folded in char.casefold():
            out.append(folded)
            index.append(origin)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def find_quote(masked_text: str, quote: str) -> tuple[int, int] | None:
    text, index = normalize(masked_text)
    needle, _ = normalize(quote)
    if not needle:
        return None
    at = text.find(needle)
    if at < 0:
        return None
    return index[at], index[at + len(needle) - 1] + 1


def injection_signs(masked_text: str) -> bool:
    normalized, _ = normalize(masked_text)
    return _INJECTION.search(normalized) is not None


def escalation_hits(
    masked_text: str, escalation: tuple[str, ...], exempt: tuple[str, ...] = EXEMPT
) -> tuple[str, ...]:
    normalized, _ = normalize(masked_text)
    covered = [m.span() for e in exempt for m in _escalation_pattern(e).finditer(normalized)]

    def counts(match: re.Match) -> bool:
        return not any(start <= match.start() < end for start, end in covered)

    return tuple(
        entry
        for entry in escalation
        if any(counts(m) for m in _escalation_pattern(entry).finditer(normalized))
    )


def _escalation_pattern(entry: str) -> re.Pattern[str]:
    prefixes = entry.casefold().split()
    body = r"\w*\s+".join(re.escape(p) for p in prefixes)
    return re.compile(r"(?<!\w)" + body)
