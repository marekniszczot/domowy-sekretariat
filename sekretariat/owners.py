"""Letter owner (D18): the person who gets reminders and closes the letter.

    before any action, any verdict, also NONE with a deadline and failed analysis:
        addressee OSOBA_n with an account ──────────────▶ that member
        addressee without account, INNA_n, NIEZNANY, none ▶ coordinator
    after an action:
        „Ogarniam” ─────────────────────────────────────▶ the member who clicked
        „Przekaż” ──────────────────────────────────────▶ the chosen member (needs an account)

Every call returns an event, also when the owner stays the same: the metric
"letters handled without forwarding" counts „Ogarniam” clicks, not owner changes.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from sekretariat.household import Member, Role

_OSOBA = re.compile(r"^OSOBA_(\d+)$")


class Cause(StrEnum):
    INITIAL = "INITIAL"
    HANDLE = "HANDLE"  # „Ogarniam” / „Zajmę się tym”
    FORWARD = "FORWARD"  # „Przekaż”


@dataclass(frozen=True)
class OwnerEvent:
    cause: Cause
    owner: str
    previous: str | None = None
    actor: str | None = None


def initial_owner(members: list[Member], addressee: str | None) -> OwnerEvent:
    """`addressee` is the analysis placeholder, or None when the analysis failed."""
    match = _OSOBA.match(addressee or "")
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(members) and members[index].has_account:
            return OwnerEvent(Cause.INITIAL, members[index].id)
    return OwnerEvent(Cause.INITIAL, coordinator(members).id)


def act(
    members: list[Member],
    previous: str,
    cause: Cause,
    actor: str,
    target: str | None = None,
) -> OwnerEvent:
    by_id = {member.id: member for member in members}
    if actor not in by_id or not by_id[actor].has_account:
        raise ValueError(f"{actor!r} cannot act on letters")

    if cause == Cause.HANDLE:
        owner = actor
    elif cause == Cause.FORWARD:
        if target not in by_id or not by_id[target].has_account:
            raise ValueError(f"cannot forward to {target!r}")
        owner = target
    else:
        raise ValueError(f"{cause} is not an action")
    return OwnerEvent(cause, owner, previous, actor)


def coordinator(members: list[Member]) -> Member:
    for member in members:
        if member.role == Role.KOORDYNATOR:
            return member
    raise ValueError("household has no coordinator")
