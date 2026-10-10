"""Selective masking: raw OCR text -> masked text for the LLM, plus an offset map.

DLP only finds sensitive spans (`inspect`). This module decides what replaces them,
so household members keep stable placeholders (OSOBA_1..N, in household order) and
quotes verified in the masked text can be mapped back to the raw text.

    raw:     "Pan Jan Nowak, PESEL 44051401359, tel. +48 600 700 800, kwota 245 zł"
              └─ PERSON_NAME ─┘     └── PESEL ──┘     └── PHONE ────┘
                  └Jan┘ member form
    masked:  "OSOBA_1, PESEL [PESEL], tel. [TELEFON], kwota 245 zł"
    segments: raw  0..13 -> masked  0..7    OSOBA_1
              raw 21..32 -> masked 15..22   [PESEL]
              raw 39..54 -> masked 29..38   [TELEFON]

Text between segments is copied unchanged, so a position after a segment moves by
that segment's length difference. A span that ends inside a segment is widened to
the whole segment in both directions.

Overlapping findings form one group, replaced as a whole:
  1. any non-person finding in the group -> its label, highest priority first
     (a member's name inside a street name stays an address);
  2. otherwise members matched in the group -> their placeholders, in order of
     appearance ("OSOBA_1" or "OSOBA_2, OSOBA_1");
  3. otherwise another person -> INNA_n, numbered per letter by spelling.

PESEL: the built-in DLP detector only fires next to the word "PESEL" and on exact
digits, so every 11-digit number (also split by spaces or dashes) is a custom
finding. A valid checksum gives [PESEL], an invalid one [NUMER], so an OCR digit
typo is still masked. A letter read in place of a digit (44O51401359) is not.
"""

import re
from dataclasses import dataclass

from google.cloud import dlp_v2

from sekretariat.household import Member

PERSON = "PERSON_NAME"
ELEVEN_DIGITS = "ELEVEN_DIGIT_NUMBER"
# RE2 (DLP) syntax: no lookarounds; \b keeps it off longer digit runs.
ELEVEN_DIGITS_PATTERN = r"\b\d(?:[ -]?\d){10}\b"

_LABELS = {
    "POLAND_PESEL_NUMBER": "PESEL",
    "POLAND_NATIONAL_ID_NUMBER": "DOWOD",
    "POLAND_PASSPORT": "PASZPORT",
    "IBAN_CODE": "IBAN",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "TELEFON",
    "STREET_ADDRESS": "ADRES",
}
_PRIORITY = ["PESEL", "DOWOD", "PASZPORT", "IBAN", "EMAIL", "TELEFON", "ADRES", "NUMER"]
DLP_INFO_TYPES = [*_LABELS, PERSON]

_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


@dataclass(frozen=True)
class Finding:
    """Sensitive span in the raw text: codepoint offsets, end exclusive."""

    start: int
    end: int
    info_type: str


@dataclass(frozen=True)
class Segment:
    raw_start: int
    raw_end: int
    masked_start: int
    masked_end: int
    replacement: str


@dataclass(frozen=True)
class MaskResult:
    masked_text: str
    segments: tuple[Segment, ...]

    def to_raw(self, start: int, end: int) -> tuple[int, int]:
        pairs = [(s.masked_start, s.masked_end, s.raw_start, s.raw_end) for s in self.segments]
        return _map_start(start, pairs), _map_end(end, pairs)

    def to_masked(self, start: int, end: int) -> tuple[int, int]:
        pairs = [(s.raw_start, s.raw_end, s.masked_start, s.masked_end) for s in self.segments]
        return _map_start(start, pairs), _map_end(end, pairs)


def pesel_valid(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:10], _PESEL_WEIGHTS, strict=True))
    return (10 - total % 10) % 10 == int(digits[10])


def member_placeholder(index: int) -> str:
    return f"OSOBA_{index + 1}"


def mask(raw_text: str, findings: list[Finding], members: list[Member]) -> MaskResult:
    spans = [_Span(f.start, f.end, _label(raw_text, f), None) for f in findings]
    spans += _member_spans(raw_text, members)

    other_people: dict[str, str] = {}
    parts: list[str] = []
    segments: list[Segment] = []
    raw_pos = masked_pos = 0
    for group in _overlap_groups(spans):
        start, end = group[0].start, max(s.end for s in group)
        replacement = _replacement(raw_text[start:end], group, other_people)

        parts.append(raw_text[raw_pos:start])
        masked_pos += start - raw_pos
        parts.append(replacement)
        segments.append(Segment(start, end, masked_pos, masked_pos + len(replacement), replacement))
        masked_pos += len(replacement)
        raw_pos = end
    parts.append(raw_text[raw_pos:])

    return MaskResult("".join(parts), tuple(segments))


def inspect(
    client: dlp_v2.DlpServiceClient, project: str, location: str, text: str
) -> list[Finding]:
    """Finds sensitive spans with DLP. Raises instead of returning a partial result."""
    response = client.inspect_content(
        request={
            "parent": f"projects/{project}/locations/{location}",
            "inspect_config": {
                "info_types": [{"name": name} for name in DLP_INFO_TYPES],
                "custom_info_types": [
                    {
                        "info_type": {"name": ELEVEN_DIGITS},
                        "regex": {"pattern": ELEVEN_DIGITS_PATTERN},
                    }
                ],
                "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
            },
            "item": {"value": text},
        }
    )
    if response.result.findings_truncated:
        raise RuntimeError("DLP truncated findings; refusing to mask partially")
    return [
        Finding(
            f.location.codepoint_range.start,
            f.location.codepoint_range.end,
            f.info_type.name,
        )
        for f in response.result.findings
    ]


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    label: str  # PERSON or a key of _PRIORITY
    member: int | None  # household index for member name matches


def _label(raw_text: str, finding: Finding) -> str:
    if finding.info_type == ELEVEN_DIGITS:
        digits = re.sub(r"\D", "", raw_text[finding.start : finding.end])
        return "PESEL" if pesel_valid(digits) else "NUMER"
    if finding.info_type == PERSON:
        return PERSON
    return _LABELS[finding.info_type]


def _member_spans(raw_text: str, members: list[Member]) -> list[_Span]:
    owner: dict[str, int] = {}
    for index, member in enumerate(members):
        for form in member.name_forms:
            key = form.casefold()
            if owner.setdefault(key, index) != index:
                raise ValueError(f"name form {form!r} belongs to more than one member")
    if not owner:
        return []

    # Longest first, so "Jana Nowaka" wins over "Jana"; spaces match OCR line breaks.
    alternatives = (
        re.escape(form).replace(r"\ ", r"\s+") for form in sorted(owner, key=len, reverse=True)
    )
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)
    return [
        _Span(m.start(), m.end(), PERSON, owner[" ".join(m.group().split()).casefold()])
        for m in pattern.finditer(raw_text)
    ]


def _overlap_groups(spans: list[_Span]) -> list[list[_Span]]:
    groups: list[list[_Span]] = []
    end = -1
    for span in sorted(spans, key=lambda s: (s.start, -s.end)):
        if groups and span.start < end:
            groups[-1].append(span)
            end = max(end, span.end)
        else:
            groups.append([span])
            end = span.end
    return groups


def _replacement(surface: str, group: list[_Span], other_people: dict[str, str]) -> str:
    labels = {s.label for s in group if s.label != PERSON}
    if labels:
        return f"[{min(labels, key=_PRIORITY.index)}]"

    members = dict.fromkeys(s.member for s in group if s.member is not None)
    if members:
        return ", ".join(member_placeholder(index) for index in members)

    key = " ".join(surface.split()).casefold()
    return other_people.setdefault(key, f"INNA_{len(other_people) + 1}")


def _map_start(pos: int, pairs: list[tuple[int, int, int, int]]) -> int:
    src_base = dst_base = 0
    for src_start, src_end, dst_start, dst_end in pairs:
        if pos < src_start:
            break
        if pos < src_end:
            return dst_start
        src_base, dst_base = src_end, dst_end
    return pos - src_base + dst_base


def _map_end(pos: int, pairs: list[tuple[int, int, int, int]]) -> int:
    src_base = dst_base = 0
    for src_start, src_end, _dst_start, dst_end in pairs:
        if pos <= src_start:
            break
        if pos <= src_end:
            return dst_end
        src_base, dst_base = src_end, dst_end
    return pos - src_base + dst_base
