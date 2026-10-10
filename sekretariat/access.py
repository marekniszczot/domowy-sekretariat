"""Who sees and does what with a letter (D16, DR-5, D17, D18). Pure functions.

    view level for a member with an account:
        uploader, addressee, current owner ───────────────▶ FULL
        coordinator, letter not private ──────────────────▶ FULL
        coordinator, letter private ──────────────────────▶ METADATA (sender type,
                                                              deadline, owner, status)
        anyone else ──────────────────────────────────────▶ NONE

    actions:
        page photos, mark as seen       FULL
        „Zajmę się tym”, „Przekaż”      FULL (private: forwarding needs confirmation,
                                          because the target will see the content)
        confirm deadline                owner or coordinator (also on private letters)
        „Zrobione”, „Otwórz ponownie”   owner, or coordinator with FULL
        „Odkryj” (make not private)     addressee or uploader
        rules, escalation list          coordinator

Letters that are not processed yet are visible only to the uploader and the
coordinator; before the verdict there is nothing to act on.
"""

import re
from enum import IntEnum

from sekretariat.household import Member, Role
from sekretariat.owners import coordinator
from sekretariat.rules import Rule

_OSOBA_IN_RULE = re.compile(r"\bOSOBA_(\d+)\b")


class View(IntEnum):
    NONE = 0
    METADATA = 1
    FULL = 2


def view_level(letter: dict, user: Member) -> View:
    if not user.has_account:
        return View.NONE
    if user.id in {letter.get("uploaded_by"), letter.get("addressee"), letter.get("owner")}:
        return View.FULL
    if user.role == Role.KOORDYNATOR:
        return View.METADATA if letter.get("private") else View.FULL
    return View.NONE


def _processed(letter: dict) -> bool:
    return letter.get("status") in {"verdict", "failed"}


def can_read(letter: dict, user: Member) -> bool:
    """Content: verdict, text and page photos."""
    return view_level(letter, user) == View.FULL


def can_act(letter: dict, user: Member) -> bool:
    """„Zajmę się tym” and „Przekaż”."""
    return (
        _processed(letter)
        and letter.get("state") == "open"
        and view_level(letter, user) == View.FULL
    )


def can_confirm_deadline(letter: dict, user: Member) -> bool:
    return (
        _processed(letter)
        and letter.get("deadline") is not None
        and (user.id == letter.get("owner") or user.role == Role.KOORDYNATOR)
        and user.has_account
    )


def can_close(letter: dict, user: Member) -> bool:
    """„Zrobione” and „Otwórz ponownie”."""
    if not _processed(letter):
        return False
    if user.id == letter.get("owner"):
        return True
    return user.role == Role.KOORDYNATOR and view_level(letter, user) == View.FULL


def can_reveal(letter: dict, user: Member) -> bool:
    return bool(letter.get("private")) and user.id in {
        letter.get("addressee"),
        letter.get("uploaded_by"),
    }


def can_configure(user: Member) -> bool:
    """„Dom”: rules, escalation list (DR-2, DR-17)."""
    return user.role == Role.KOORDYNATOR


def forward_targets(household: list[Member], user: Member) -> list[Member]:
    return [m for m in household if m.has_account and m.id != user.id]


def forward_suggestion(
    letter: dict, household: list[Member], rules: list[Rule], user: Member
) -> Member | None:
    """D17: the member named in the deciding rule, otherwise the coordinator."""
    targets = {m.id: m for m in forward_targets(household, user)}
    rule_id = (letter.get("analysis") or {}).get("rule_id")
    rule = next((r for r in rules if r.id == rule_id), None)
    if rule is not None:
        for match in _OSOBA_IN_RULE.finditer(rule.text):
            index = int(match.group(1)) - 1
            if 0 <= index < len(household) and household[index].id in targets:
                return household[index]
    lead = coordinator(household)
    return targets.get(lead.id)
