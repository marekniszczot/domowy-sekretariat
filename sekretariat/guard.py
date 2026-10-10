"""Deterministic guard: the model proposes a verdict, code decides whether to trust it.

    LlmFailure ───────────────────────────────────────────▶ FORWARD [MODEL_FAILED]
    LetterAnalysis
      ├─ addressee OSOBA_n outside the household ──────────▶ FORWARD [BAD_ADDRESSEE]
      ├─ any *_quote not found in normalized masked text ─▶ FORWARD [QUOTE_NOT_FOUND]
      ├─ rule_id unknown ──────────────────────────────────▶ FORWARD [UNKNOWN_RULE]
      ├─ rule_id null with NONE or SELF ───────────────────▶ FORWARD [MISSING_RULE]
      ├─ confidence < threshold ───────────────────────────▶ FORWARD [LOW_CONFIDENCE]
      ├─ escalation entry in masked text ──────────────────▶ FORWARD [ESCALATION]
      └─ none of the above ────────────────────────────────▶ model verdict

All checks run, so every reason is reported. ESCALATION means "urgent" in the UI;
the other reasons mean "not sure, forward it".

Quote normalization (same for text and quote): words split by a hyphen at a line
end are joined, whitespace runs become one space, case is folded, typographic
quotes and dashes become ASCII. Each normalized character remembers its position
in the masked text, so a found quote yields an exact masked span for highlighting.

Escalation entries are word prefixes: "urz skarbow" matches "Urzędu Skarbowego",
"komorni" matches "komornika" and "komorniczej".
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
    "urz skarbow",
    "wezwani do zapłat",
)
QUOTE_FIELDS = ("rule_trigger_quote", "deadline_quote", "consequence_quote")

_PUNCTUATION = str.maketrans({"„": '"', "”": '"', "“": '"', "‚": "'", "‘": "'", "’": "'",
                              "–": "-", "—": "-", " ": " "})  # fmt: skip
_LINE_END_HYPHEN = re.compile(r"(?<=\w)-[ \t]*\r?\n\s*(?=\w)")
_OSOBA = re.compile(r"^OSOBA_(\d+)$")


class Reason(StrEnum):
    MODEL_FAILED = "MODEL_FAILED"
    BAD_ADDRESSEE = "BAD_ADDRESSEE"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    UNKNOWN_RULE = "UNKNOWN_RULE"
    MISSING_RULE = "MISSING_RULE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
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
    normalized, _ = normalize(masked_text)
    hits = tuple(entry for entry in escalation if _escalation_pattern(entry).search(normalized))
    escalation_reasons = (Reason.ESCALATION,) if hits else ()

    if isinstance(outcome, LlmFailure):
        reasons = (Reason.MODEL_FAILED, *escalation_reasons)
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


def _escalation_pattern(entry: str) -> re.Pattern[str]:
    prefixes = entry.casefold().split()
    body = r"\w*\s+".join(re.escape(p) for p in prefixes)
    return re.compile(r"(?<!\w)" + body)
