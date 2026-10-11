"""„Masz nowe pismo do ogarnięcia” (DR-12, DT8) and failed analysis (D6).

    „Przekaż” to someone else ──┐  letter.assigned = {to, by, at, cause}
    analysis failed (D6) ───────┤  (cause FORWARD / FAILED; by is None for FAILED)
                                ▼
    schedule(member): a Cloud Task /internal/notify/{member} at
        max(now + 2 min, last e-mail + 15 min)     2 min: past the undo window
        (none if one is already waiting: it will take this letter too)
                                ▼
    send(member): one e-mail with every letter assigned to them since the last one
        that is still theirs, open and not taken („Cofnij” and
        „Zajmę się tym” cancel it); an SMTP error raises, Cloud Tasks retries

`notices/{member}` keeps {sent_at, scheduled_at}. The e-mail carries metadata
only (D7), like the reminders.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from sekretariat import emails
from sekretariat.emails import Item, deadline_words, plural
from sekretariat.household import Member
from sekretariat.mailer import Email, Mailer
from sekretariat.store import Store
from sekretariat.web.present import deadline_date, sender_label

log = logging.getLogger(__name__)

DELAY = timedelta(minutes=2)  # the server keeps „Cofnij” for 60 s
GAP = timedelta(minutes=15)
FORWARD = "FORWARD"
FAILED = "FAILED"


def assigned(to: str, by: str | None, at: datetime, cause: str) -> dict:
    return {"to": to, "by": by, "at": at, "cause": cause}


def schedule(
    store: Store, enqueue: Callable[[str, datetime], None], member_id: str, at: datetime
) -> None:
    state = store.notice(member_id)
    scheduled = state.get("scheduled_at")
    if scheduled is not None and scheduled >= at:
        return
    send_at = at + DELAY
    if state.get("sent_at") is not None:
        send_at = max(send_at, state["sent_at"] + GAP)
    store.set_notice(member_id, {"scheduled_at": send_at})
    enqueue(member_id, send_at)


def pending(letter: dict, member_id: str, since: datetime | None, until: datetime) -> bool:
    assignment = letter.get("assigned") or {}
    return (
        assignment.get("to") == member_id
        and assignment.get("by") != member_id
        and letter.get("owner") == member_id
        and letter.get("state") == "open"
        and not letter.get("taken")
        and (since is None or assignment["at"] > since)
        and assignment["at"] <= until
    )


def send(
    store: Store,
    household: list[Member],
    mailer: Mailer,
    base_url: str,
    member_id: str,
    at: datetime,
    day: date,
) -> int:
    """Sends the batch for `member_id`; returns the number of letters in it."""
    member = next((m for m in household if m.id == member_id), None)
    if member is None or member.notify_email is None:
        log.warning("notice for %s skipped: no such member or no e-mail", member_id)
        return 0
    # Cleared first: an assignment made while this runs schedules its own task.
    store.set_notice(member_id, {"scheduled_at": None})
    since = store.notice(member_id).get("sent_at")
    letters = [letter for letter in store.list_letters() if pending(letter, member_id, since, at)]
    if letters:
        mailer.send(member.notify_email, compose(letters, day, base_url))
        store.set_notice(member_id, {"sent_at": at})
        log.info("notified %s about %d letter(s)", member_id, len(letters))
    return len(letters)


def compose(letters: list[dict], day: date, base_url: str) -> Email:
    ordered = sorted(letters, key=lambda letter: letter["assigned"]["at"])
    items = [_item(letter, day, base_url) for letter in ordered]
    if len(ordered) > 1:
        count = len(ordered)
        noun = plural(count, "nowe pismo", "nowe pisma", "nowych pism")
        subject = f"Masz {count} {noun} do ogarnięcia"
    elif ordered[0]["assigned"]["cause"] == FAILED:
        subject = "Nie udało się przeanalizować pisma"
    else:
        subject = f"Masz nowe pismo do ogarnięcia: {items[0].title}"
    intro = (
        "Masz nowe pisma do ogarnięcia." if len(ordered) > 1 else ("Masz nowe pismo do ogarnięcia.")
    )
    return emails.compose(subject, intro, items, emails.CONTENT_IN_APP)


def _item(letter: dict, day: date, base_url: str) -> Item:
    link = f"{base_url}/pisma/{letter['id']}"
    if letter["assigned"]["cause"] == FAILED:
        return Item(
            title=sender_label(None),
            line="Nie udało się go przeanalizować",
            link=link,
            note="Przejrzyj je w aplikacji i zdecyduj, co dalej.",
        )
    due = deadline_date(letter)
    title = sender_label((letter.get("analysis") or {}).get("sender_type"))
    if due is None:
        return Item(title=title, line="bez terminu", link=link)
    confirmed = bool(letter["deadline"].get("confirmed"))
    return Item(
        title=title,
        line=deadline_words(due, confirmed, day),
        link=link,
        note="" if confirmed else "Termin niezatwierdzony, sprawdź go w aplikacji.",
        urgent=(due - day).days <= 3,
    )
