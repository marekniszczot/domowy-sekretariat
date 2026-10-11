"""Deadline reminders (D3): which owner gets an e-mail about which letter, and when.

    open letter with a deadline (confirmed or not; also NONE), days left d:
        d > 3 ───────▶ nothing
        d ≤ 3 ───────▶ T-3 ┐  each step once; a letter that arrives late gets only
        d ≤ 1 ───────▶ T-1 ├  the sharpest step, the milder ones count as sent
        d = 0 ───────▶ T-0 ┘
        d < 0 ───────▶ OVERDUE, once a day until „Zrobione”

    `reminded` on the letter: {date, owner, steps, overdue_on}
        another deadline date or another owner ──▶ starts over
        written only after the e-mail went out ──▶ a failed send is retried by the
                                                   next run (D8)

One e-mail per owner and run, listing their letters. The e-mail carries metadata
only (D7): sender type, deadline, whether it is confirmed, a link that needs
sign-in. `Reminder` holds nothing else, so letter content cannot reach it.

Runs from the daily job (07:00 Europe/Warsaw) and right after a letter gets its
verdict or its deadline is corrected (`letter_ids`).
"""

import html
import logging
import smtplib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from sekretariat.household import Member
from sekretariat.mailer import Email, Mailer
from sekretariat.store import Store
from sekretariat.web.present import countdown, deadline_date, on_date, sender_label, until_date

log = logging.getLogger(__name__)

HOME_ZONE = ZoneInfo("Europe/Warsaw")


class Step(StrEnum):
    T3 = "T-3"
    T1 = "T-1"
    T0 = "T-0"
    OVERDUE = "OVERDUE"


ORDER = [Step.T3, Step.T1, Step.T0]


@dataclass(frozen=True)
class Reminder:
    letter_id: str
    owner: str
    step: Step
    due: date
    confirmed: bool
    sender_type: str | None


@dataclass
class Outcome:
    sent: int = 0  # letters reminded
    failed: int = 0  # letters left for the next run


def today() -> date:
    return datetime.now(HOME_ZONE).date()


def due_step(letter: dict, day: date) -> Step | None:
    if letter.get("state") != "open" or not letter.get("owner"):
        return None
    due = deadline_date(letter)
    if due is None:
        return None
    days = (due - day).days
    if days > 3:
        return None
    sent = _sent(letter)
    if days < 0:
        return None if sent.get("overdue_on") == day.isoformat() else Step.OVERDUE
    step = Step.T0 if days == 0 else Step.T1 if days == 1 else Step.T3
    return None if step in sent.get("steps", []) else step


def mark(letter: dict, step: Step, day: date) -> dict:
    """`reminded` after the e-mail about `step` went out."""
    sent = _sent(letter)
    reminded = {
        "date": letter["deadline"]["date"],
        "owner": letter["owner"],
        "steps": list(sent.get("steps", [])),
        "overdue_on": sent.get("overdue_on"),
    }
    if step == Step.OVERDUE:
        reminded["overdue_on"] = day.isoformat()
    else:
        # Days only go down for one date, so the steps sent before are milder ones.
        reminded["steps"] = [s.value for s in ORDER[: ORDER.index(step) + 1]]
    return reminded


def _sent(letter: dict) -> dict:
    reminded = letter.get("reminded") or {}
    if (
        reminded.get("date") != letter["deadline"]["date"]
        or reminded.get("owner") != letter["owner"]
    ):
        return {}
    return reminded


def collect(letters: Iterable[dict], day: date) -> list[Reminder]:
    reminders = []
    for letter in letters:
        step = due_step(letter, day)
        if step is not None:
            reminders.append(
                Reminder(
                    letter_id=letter["id"],
                    owner=letter["owner"],
                    step=step,
                    due=deadline_date(letter),
                    confirmed=bool(letter["deadline"].get("confirmed")),
                    sender_type=(letter.get("analysis") or {}).get("sender_type"),
                )
            )
    return reminders


def remind(
    store: Store,
    household: list[Member],
    mailer: Mailer,
    base_url: str,
    day: date,
    letter_ids: Iterable[str] | None = None,
) -> Outcome:
    if letter_ids is None:
        letters = store.list_letters()
    else:
        letters = [
            {"id": i, **letter} for i in letter_ids if (letter := store.get_letter(i)) is not None
        ]
    by_id = {letter["id"]: letter for letter in letters}
    by_owner: dict[str, list[Reminder]] = {}
    for reminder in collect(letters, day):
        by_owner.setdefault(reminder.owner, []).append(reminder)

    members = {member.id: member for member in household}
    outcome = Outcome()
    for owner, reminders in by_owner.items():
        member = members.get(owner)
        address = member.notify_email if member else None
        if address is None:
            log.warning("owner %s has no e-mail; %d letter(s) skipped", owner, len(reminders))
            outcome.failed += len(reminders)
            continue
        try:
            mailer.send(address, compose(reminders, day, base_url))
        except (smtplib.SMTPException, OSError):
            log.warning("reminder to %s failed; the next run retries", owner, exc_info=True)
            outcome.failed += len(reminders)
            continue
        for reminder in reminders:
            reminded = mark(by_id[reminder.letter_id], reminder.step, day)
            store.update_letter(reminder.letter_id, {"reminded": reminded})
        outcome.sent += len(reminders)
        log.info("reminded %s about %d letter(s)", owner, len(reminders))
    return outcome


# E-mail (D7: metadata only)

_INK = "#1D2A5C"
_MUTED = "#5B6478"
_RULE = "#DDE0E6"
_URGENT = "#B3261E"
_GROUND = "#F4F5F7"
_FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def compose(reminders: list[Reminder], day: date, base_url: str) -> Email:
    ordered = sorted(reminders, key=lambda r: (r.due, r.letter_id))
    first = ordered[0]
    subject = f"{_headline(first, day)}: {sender_label(first.sender_type)}"
    if len(ordered) > 1:
        subject += f" i {_others(len(ordered) - 1)}"

    many = len(ordered) > 1
    intro = "Przypomnienie o terminach pism." if many else "Przypomnienie o terminie pisma."
    outro = (
        "Pismo zamkniesz w aplikacji przyciskiem „Zrobione”, wtedy przypomnienia ustaną. "
        "Treść pism jest tylko w aplikacji, po zalogowaniu."
    )

    text_items = []
    html_items = []
    for reminder in ordered:
        sender = sender_label(reminder.sender_type)
        when = _when(reminder, day)
        link = f"{base_url}/pisma/{reminder.letter_id}"
        note = "" if reminder.confirmed else "Termin niezatwierdzony, sprawdź go w aplikacji."
        text_items.append("\n".join(filter(None, [f"▲ {sender}: {when}", note, link])))
        html_items.append(
            f'<div style="border-top:1px solid {_RULE};padding:16px 0;">'
            f'<p style="margin:0;font-weight:700;">{html.escape(sender)}</p>'
            f'<p style="margin:4px 0 0;color:{_URGENT};font-weight:700;">▲ {html.escape(when)}</p>'
            + (f'<p style="margin:4px 0 0;color:{_MUTED};">{html.escape(note)}</p>' if note else "")
            + f'<p style="margin:12px 0 0;"><a href="{html.escape(link)}" '
            f'style="display:inline-block;background:{_INK};color:#FFFFFF;'
            f'text-decoration:none;font-weight:700;padding:14px 20px;border-radius:6px;">'
            "Otwórz pismo</a></p></div>"
        )

    text = "\n\n".join([intro, *text_items, outro, "Domowy Sekretariat"]) + "\n"
    body = (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;background:{_GROUND};">'
        f'<div style="max-width:560px;margin:0 auto;padding:24px 16px;font-family:{_FONT};'
        f'font-size:18px;line-height:1.5;color:{_INK};">'
        f'<p style="margin:0 0 16px;">{html.escape(intro)}</p>'
        + "".join(html_items)
        + f'<p style="margin:16px 0 0;border-top:1px solid {_RULE};padding-top:16px;'
        f'font-size:15px;color:{_MUTED};">{html.escape(outro)}</p>'
        f'<p style="margin:8px 0 0;font-size:15px;color:{_MUTED};">Domowy Sekretariat</p>'
        "</div></body></html>"
    )
    return Email(subject, text, body)


def _headline(reminder: Reminder, day: date) -> str:
    if reminder.step == Step.OVERDUE:
        return "Po terminie"
    words = countdown(reminder.due, day)
    return f"{words[:1].upper()}{words[1:]} termin"


def _when(reminder: Reminder, day: date) -> str:
    if reminder.step == Step.OVERDUE:
        return f"termin minął {on_date(reminder.due, day)}"
    until = until_date(reminder.due, day)
    if not reminder.confirmed:
        until = f"najpóźniej {until}"
    return f"{countdown(reminder.due, day)} · {until}"


def _others(count: int) -> str:
    if count == 1:
        return "1 inne pismo"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} inne pisma"
    return f"{count} innych pism"
