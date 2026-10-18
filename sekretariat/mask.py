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

Household names are found without DLP, only when each word starts with a capital
letter (a form may also be a common word: "Wilk" vs "wilk"). First names and surnames are configured
separately and matched in both orders ("Jan Nowak", "Nowak Jan", "Nowak, Jan",
also across a line break) -> the first name's owner. A surname alone belongs to
its member when only one member has it; a surname shared by several members
(the family name) becomes OSOBA_DOMU, a household member without knowing who.

PESEL: the built-in DLP detector only fires next to the word "PESEL" and on exact
digits, so every 11-digit number (also split by spaces or dashes) is a custom
finding. A valid checksum gives [PESEL], an invalid one [NUMER], so an OCR digit
typo is still masked. A letter read in place of a digit (44O51401359) is not.

Addresses: the built-in DLP detector misses the Polish flat notation ("ul. Lipowa 7
m. 3") and a street inside a sentence, so streets with a prefix and a number and
postal codes (with the city after them) are custom findings too. Each member's
address forms ("Lipowa 7", "Lipowej 7") are found without DLP, in any case, also
without a prefix ("Wspólnota Mieszkaniowa Lipowa 7"). All of them become [ADRES].
The prefix stays, as with the built-in detector, and address groups separated only
by commas or whitespace become one [ADRES]: the model reads "ul. [ADRES]" far more
reliably than "[ADRES], [ADRES]" (eval: verdicts flipped on that alone).

    raw:     "ul. Lipowa 7 m. 3, 00-001 Warszawa"
                 └ street ───┘  └ postal code ──┘
    masked:  "ul. [ADRES]"
"""

import re
from dataclasses import dataclass

from google.cloud import dlp_v2

from sekretariat.household import Member

PERSON = "PERSON_NAME"
ELEVEN_DIGITS = "ELEVEN_DIGIT_NUMBER"
# RE2 (DLP) syntax: no lookarounds; \b keeps it off longer digit runs.
ELEVEN_DIGITS_PATTERN = r"\b\d(?:[ -]?\d){10}\b"

POLISH_STREET = "POLISH_STREET"
POSTAL_CODE = "POSTAL_CODE"
# RE2 (DLP) and Python: \w and \b are ASCII in RE2, so Polish letters are listed.
_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
_LOWER = "a-ząćęłńóśźż"
_STREET_PREFIX = (
    r"(?i:\b(?:ul|al|os|pl)\.|\b(?:ulica|ulicy|aleja|alei|osiedle|osiedlu|plac|placu)\b)"
)
_STREET_WORD = rf"[0-9{_UPPER}][0-9{_UPPER}{_LOWER}.'-]*"
_FLAT = r"(?:[ \t]*/[ \t]*\d+[A-Za-z]?|[ \t]*,?[ \t]*(?:m|lok|lokal|mieszk)\.?[ \t]*\d+[A-Za-z]?)?"
# "ul. Lipowa 7 m. 3", "al. Jana Pawła II 15a lok. 2"; one line only. Group 1 is the
# street without its prefix, the only part DLP reports.
STREET_PATTERN = (
    rf"{_STREET_PREFIX}[ \t]*({_STREET_WORD}(?:[ \t]+{_STREET_WORD}){{0,3}}?"
    rf"[ \t]+\d+[A-Za-z]?{_FLAT})"
)
_CITY = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
# "00-001 Warszawa", "43-300 Bielsko-Biała"; the city only on the same line.
POSTAL_CODE_PATTERN = rf"\b\d{{2}}-\d{{3}}\b(?:[ \t]+{_CITY}(?:[ \t]+{_CITY})?)?"

_CUSTOM_REGEXES = {
    ELEVEN_DIGITS: {"pattern": ELEVEN_DIGITS_PATTERN},
    POLISH_STREET: {"pattern": STREET_PATTERN, "group_indexes": [1]},
    POSTAL_CODE: {"pattern": POSTAL_CODE_PATTERN},
}

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


HOUSEHOLD = -1  # member index of a surname shared by several members
HOUSEHOLD_PLACEHOLDER = "OSOBA_DOMU"


def member_placeholder(index: int) -> str:
    return HOUSEHOLD_PLACEHOLDER if index == HOUSEHOLD else f"OSOBA_{index + 1}"


def mask(raw_text: str, findings: list[Finding], members: list[Member]) -> MaskResult:
    spans = [_Span(f.start, f.end, _label(raw_text, f), None) for f in findings]
    spans += _member_spans(raw_text, members)
    spans += address_spans(raw_text, members)

    other_people: dict[str, str] = {}
    parts: list[str] = []
    segments: list[Segment] = []
    raw_pos = masked_pos = 0
    for group in _join_addresses(raw_text, _overlap_groups(spans)):
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
                    {"info_type": {"name": name}, "regex": regex}
                    for name, regex in _CUSTOM_REGEXES.items()
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
    if finding.info_type in (POLISH_STREET, POSTAL_CODE):
        return "ADRES"
    if finding.info_type == PERSON:
        return PERSON
    return _LABELS[finding.info_type]


def _member_spans(raw_text: str, members: list[Member]) -> list[_Span]:
    first_owner: dict[str, int] = {}
    surname_owners: dict[str, set[int]] = {}
    for index, member in enumerate(members):
        for form in member.first_name_forms:
            if first_owner.setdefault(_key(form), index) != index:
                raise ValueError("a first name form belongs to more than one member")
        for form in member.surname_forms:
            surname_owners.setdefault(_key(form), set()).add(index)
    if set(first_owner) & set(surname_owners):
        raise ValueError("a form is both a first name and a surname")
    if not first_owner and not surname_owners:
        return []

    first = _alternatives(first_owner)
    surname = _alternatives(surname_owners)
    sep = r"(?:\s*,\s*|\s+)"
    options = []
    if first_owner and surname_owners:
        options += [rf"(?P<f1>{first}){sep}{surname}", rf"{surname}{sep}(?P<f2>{first})"]
    if first_owner:
        options.append(rf"(?P<f3>{first})")
    if surname_owners:
        options.append(rf"(?P<s>{surname})")
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(options) + r")(?!\w)")

    spans = []
    for match in pattern.finditer(raw_text):
        groups = match.groupdict()
        first_name = groups.get("f1") or groups.get("f2") or groups.get("f3")
        if first_name:
            index = first_owner[_key(first_name)]
        else:
            owners = surname_owners[_key(groups["s"])]
            index = next(iter(owners)) if len(owners) == 1 else HOUSEHOLD
        spans.append(_Span(match.start(), match.end(), PERSON, index))
    return spans


def address_spans(raw_text: str, members: list[Member]) -> list[_Span]:
    forms = sorted({f for m in members for f in m.address_forms}, key=len, reverse=True)
    if not forms:
        return []
    alternatives = [r"\s+".join(re.escape(word) for word in f.split()) for f in forms]
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", re.IGNORECASE)
    return [_Span(m.start(), m.end(), "ADRES", None) for m in pattern.finditer(raw_text)]


def _key(form: str) -> str:
    return " ".join(form.split()).casefold()


def _alternatives(forms) -> str:
    # Longest first, so "Maria Teresa" wins over "Maria".
    return "(?:" + "|".join(name_pattern(f) for f in sorted(forms, key=len, reverse=True)) + ")"


def name_pattern(form: str) -> str:
    """Each word must start with a capital letter, the rest may be any case:
    "Wilk" matches "Wilk" and "WILK" but not the noun "wilk"."""
    words = []
    for word in form.split():
        rest = f"(?i:{re.escape(word[1:])})" if len(word) > 1 else ""
        words.append(re.escape(word[0].upper()) + rest)
    return r"\s+".join(words)  # whitespace also matches OCR line breaks


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


def _join_addresses(raw_text: str, groups: list[list[_Span]]) -> list[list[_Span]]:
    joined: list[list[_Span]] = []
    for group in groups:
        if joined and _is_address(joined[-1]) and _is_address(group):
            gap = raw_text[max(s.end for s in joined[-1]) : group[0].start]
            if not gap.strip(" \t\r\n,"):
                joined[-1] = joined[-1] + group
                continue
        joined.append(group)
    return joined


def _is_address(group: list[_Span]) -> bool:
    labels = {s.label for s in group if s.label != PERSON}
    return bool(labels) and min(labels, key=_PRIORITY.index) == "ADRES"


def _replacement(surface: str, group: list[_Span], other_people: dict[str, str]) -> str:
    labels = {s.label for s in group if s.label != PERSON}
    if labels:
        return f"[{min(labels, key=_PRIORITY.index)}]"

    members = dict.fromkeys(s.member for s in group if s.member is not None)
    if len(members) > 1:
        members.pop(HOUSEHOLD, None)  # the named members say who it is
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
