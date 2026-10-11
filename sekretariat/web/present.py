"""How a letter reads on screen: four states (DR-4), dates in words, list groups (DR-3).

Pure functions over the letter fields written by pipeline.py and letters.py; the
codes NONE/SELF/FORWARD and guard reasons never reach the page (DESIGN.md).

    status received/ocr_done/masked ───────────────────────▶ (processing, no state)
    status unreadable or failed ───────────────────────────▶ ? unsure
    reason ESCALATION ─────────────────────────────────────▶ ▲ urgent
    verdict NONE ──────────────────────────────────────────▶ ✓ ok
    open, deadline in ≤ 3 days or overdue ─────────────────▶ ▲ urgent
    any other guard reason ────────────────────────────────▶ ? unsure
    otherwise (SELF, FORWARD) ─────────────────────────────▶ ● todo
"""

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from sekretariat.household import Member

PROCESSING = {"received", "ocr_done", "masked"}
URGENT_DAYS = 3
THIS_WEEK_DAYS = 7
# "Pewne" vs "Sprawdź" (DR-10). Placeholder until calibration (T11); the guard
# already forwards everything below 0.8.
CERTAIN = 0.9


class State(StrEnum):
    OK = "ok"
    TODO = "todo"
    UNSURE = "unsure"
    URGENT = "urgent"


ICON = {State.OK: "✓", State.TODO: "●", State.UNSURE: "?", State.URGENT: "▲"}
LABEL = {
    State.OK: "Nic nie musisz robić",
    State.TODO: "Do zrobienia",
    State.UNSURE: "Nie mam pewności",
    State.URGENT: "Pilne",
}

SENDERS = {
    "BANK": "Bank",
    "URZAD": "Urząd",
    "UBEZPIECZYCIEL": "Ubezpieczyciel",
    "WSPOLNOTA": "Wspólnota mieszkaniowa",
    "TELEKOMUNIKACJA": "Operator telekomunikacyjny",
    "ENERGIA": "Dostawca energii",
    "PRACODAWCA": "Pracodawca",
    "ZUS": "ZUS",
    "PRZYCHODNIA": "Przychodnia",
    "INNY": "Inny nadawca",
}

# First matching reason wins; ESCALATION is not "unsure", it is urgent.
_UNSURE_REASONS = [
    ({"ANALYSIS_FAILED", "MODEL_FAILED"}, "nie udało się przeanalizować"),
    ({"QUOTE_NOT_FOUND"}, "cytat nie zgadza się z pismem"),
    ({"LOW_CONFIDENCE"}, "niska pewność"),
    ({"UNKNOWN_RULE", "MISSING_RULE"}, "żadna zasada nie pasuje"),
    ({"BAD_ADDRESSEE"}, "adresat spoza domu"),
]

_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
           "sierpnia", "września", "października", "listopada", "grudnia"]  # fmt: skip
_UNTIL = ["poniedziałku", "wtorku", "środy", "czwartku", "piątku", "soboty", "niedzieli"]
_ON = ["w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę",
       "w niedzielę"]  # fmt: skip

# The model sometimes inflects placeholders („dla OSOBY_1”, „OSOBIE_2”); the
# name stays in the nominative then, which still reads better than a code.
_OSOBA = re.compile(r"\bOSOB[A-ZĄĘ]*_(\d+)\b")
_INNA = re.compile(r"\bINNA(?:_\d+)?\b|\bINN[A-ZĄĘ]+_\d+\b")


# State


def _reasons(letter: dict) -> set[str]:
    return set(letter.get("reasons") or [])


def deadline_date(letter: dict) -> date | None:
    deadline = letter.get("deadline")
    return date.fromisoformat(deadline["date"]) if deadline else None


def _confirmed(letter: dict) -> bool:
    return bool((letter.get("deadline") or {}).get("confirmed"))


def _open(letter: dict) -> bool:
    return letter.get("state") != "closed"


def state(letter: dict, today: date) -> State | None:
    status = letter.get("status")
    if status in PROCESSING:
        return None
    if status in {"unreadable", "failed"}:
        return State.UNSURE
    reasons = _reasons(letter)
    if "ESCALATION" in reasons:
        return State.URGENT
    if letter.get("verdict") == "NONE":
        return State.OK
    due = deadline_date(letter)
    if _open(letter) and due is not None and (due - today).days <= URGENT_DAYS:
        return State.URGENT
    return State.UNSURE if reasons else State.TODO


def unsure_reason(letter: dict) -> str | None:
    if letter.get("status") == "unreadable":
        return "zdjęcie nieczytelne"
    reasons = _reasons(letter)
    for codes, words in _UNSURE_REASONS:
        if reasons & codes:
            return words
    return None


def verb(letter: dict, today: date) -> str:
    """The stamp's main line. Placeholders are replaced later (with_names)."""
    if letter.get("status") == "unreadable":
        return "Zrób zdjęcie jeszcze raz"
    if letter.get("verdict") == "NONE":
        return "Zachowaj do wiadomości"
    if state(letter, today) == State.UNSURE or unsure_reason(letter):
        if "ESCALATION" not in _reasons(letter):
            return "Przekaż dalej"
    action = ((letter.get("analysis") or {}).get("required_action") or "").strip()
    return action.removesuffix(".") or "Zajmij się tym pismem"


def when_line(letter: dict, today: date) -> str:
    due = deadline_date(letter)
    if due is None:
        return unsure_reason(letter) or "bez terminu"
    if _open(letter) and due < today:
        return f"termin minął {on_date(due, today)}"
    until = until_date(due, today)
    if not _confirmed(letter):
        until = f"najpóźniej {until}"
    return f"{countdown(due, today)} · {until}"


def stamp_label(letter: dict, today: date, verb_text: str) -> str:
    """What VoiceOver reads for the stamp (DESIGN.md, Components): one sentence each."""
    current = state(letter, today)
    when = when_line(letter, today).replace(" · ", ", ")
    return f"{LABEL[current]}. {verb_text}. {when[:1].upper()}{when[1:]}."


def confidence_word(letter: dict) -> str:
    if unsure_reason(letter):
        return "Sprawdź"  # the guard overrode the model, whatever it claimed
    confidence = (letter.get("analysis") or {}).get("confidence")
    return "Pewne" if confidence is not None and confidence >= CERTAIN else "Sprawdź"


# Dates in words


def countdown(day: date, today: date, short: bool = False) -> str:
    days = (day - today).days
    if days == 0:
        return "dziś"
    if days == 1:
        return "jutro"
    if days > 1:
        return f"za {days} dni"
    late = -days
    unit = "dzień" if late == 1 else "dni"
    return f"{late} {unit} po" if short else f"{late} {unit} po terminie"


def _day_month(day: date, today: date) -> str:
    text = f"{day.day} {_MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def until_date(day: date, today: date) -> str:
    return f"do {_UNTIL[day.weekday()]}, {_day_month(day, today)}"


def on_date(day: date, today: date) -> str:
    return f"{_ON[day.weekday()]}, {_day_month(day, today)}"


def short_date(day: date) -> str:
    return f"{day.day:02d}.{day.month:02d}"


def delivered(day: date, today: date) -> str:
    days = (today - day).days
    if days == 0:
        return "przyszło dziś"
    if days == 1:
        return "przyszło wczoraj"
    return f"przyszło {_day_month(day, today)}"


# Text


def sender_label(sender_type: str | None) -> str:
    if sender_type is None:
        return "Nowe pismo"
    return SENDERS.get(sender_type, SENDERS["INNY"])


def with_names(text: str, household: list[Member]) -> str:
    """OSOBA_n → the member's name, for people who may already see the content."""

    def member(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        return household[index].name if 0 <= index < len(household) else match.group(0)

    text = text.replace("OSOBA_DOMU", "Wasz dom")
    return _INNA.sub("inna osoba", _OSOBA.sub(member, text))


def quote_context(raw: str, span: tuple[int, int], radius: int = 80) -> tuple[str, str, str]:
    """(before, quote, after) around a span of the raw text, cut at word boundaries."""
    start, end = span
    before = raw[max(0, start - radius) : start]
    if start - radius > 0:
        if not raw[start - radius - 1].isspace():
            before = re.sub(r"^\S+", "", before)  # the cut word
        before = "…" + before.lstrip()
    after = raw[end : end + radius]
    if end + radius < len(raw):
        if not raw[end + radius].isspace():
            after = re.sub(r"\S+$", "", after)
        after = after.rstrip() + "…"

    def flat(text: str) -> str:
        return re.sub(r"\s+", " ", text)

    return flat(before), flat(raw[start:end]), flat(after)


# Lists (DR-3)


@dataclass
class Group:
    title: str
    letters: list[dict] = field(default_factory=list)


_GROUPS = ["W trakcie", "Po terminie", "Do sprawdzenia", "Ten tydzień",
           "Później i bez terminu", "Zrobione"]  # fmt: skip


def group_title(letter: dict, today: date) -> str:
    if letter.get("status") in PROCESSING:
        return "W trakcie"
    if not _open(letter):
        return "Zrobione"
    due = deadline_date(letter)
    if due is not None and due < today and letter.get("verdict") != "NONE":
        return "Po terminie"
    if state(letter, today) == State.UNSURE or (due is not None and not _confirmed(letter)):
        return "Do sprawdzenia"
    if due is not None and (due - today).days <= THIS_WEEK_DAYS:
        return "Ten tydzień"
    return "Później i bez terminu"


def group(letters: list[dict], today: date) -> list[Group]:
    """Empty groups are left out; inside a group the nearest deadline comes first."""
    groups = {title: Group(title) for title in _GROUPS}
    for letter in letters:
        groups[group_title(letter, today)].letters.append(letter)

    def order(letter: dict):
        due = deadline_date(letter)
        created = letter.get("created_at")
        return (due or date.max, -created.timestamp() if created else 0)

    result = []
    for g in groups.values():
        if g.letters:
            g.letters.sort(key=order)
            result.append(g)
    return result


@dataclass(frozen=True)
class Row:
    """One list row (DESIGN.md, Listy): mini stamp, sender, owner, countdown, state word."""

    href: str
    mini: str  # CSS classes of the mini stamp
    icon: str  # state icon, or "lock" for a private letter
    who: str
    sub: str
    count: str
    word: str
    tone: str  # CSS class of the state word
    new: bool = False


def row(letter: dict, full: bool, user: Member, household: list[Member], today: date) -> Row:
    names = {m.id: m.name for m in household}
    href = f"/pisma/{letter['id']}"
    who = sender_label(
        letter.get("sender_type") or (letter.get("analysis") or {}).get("sender_type")
    )
    owner = names.get(letter.get("owner"), "")
    due = deadline_date(letter)
    count = countdown(due, today, short=True) if due and _open(letter) else "—"
    if letter.get("status") in PROCESSING:
        return Row(href, "mini pending", "…", who, "Czytam pismo…", "", "", "muted")
    if not full:
        sub = " · ".join(filter(None, [owner, "prywatne"]))
        return Row(href, "mini private", "lock", who, sub, count, "Prywatne", "muted")

    current = state(letter, today)
    unconfirmed = due is not None and not _confirmed(letter) and _open(letter)
    details = [owner]
    if unconfirmed:
        details.append(f"najpóźniej {short_date(due)}")
    if reason := unsure_reason(letter):
        details.append(reason)
    mini = f"mini {current}"
    word, tone = LABEL[current], f"t-{current}"
    if not _open(letter):
        word, tone = "Zrobione", "muted"
    elif unconfirmed and current in {State.TODO, State.URGENT}:
        mini += " half"
        if current == State.TODO:
            word = "Sprawdź termin"
    new = letter.get("status") in {"verdict", "failed", "unreadable"} and user.id not in (
        letter.get("seen_by") or []
    )
    return Row(
        href, mini, ICON[current], who, " · ".join(filter(None, details)), count, word, tone, new
    )
