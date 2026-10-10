import pytest

from sekretariat.access import (
    View,
    can_act,
    can_close,
    can_confirm_deadline,
    can_reveal,
    forward_suggestion,
    forward_targets,
    view_level,
)
from sekretariat.household import Member, Role
from sekretariat.rules import Rule

DOM1 = Member("dom1", Role.DOMOWNIK)
KOORD = Member("koord", Role.KOORDYNATOR)
SENIOR = Member("senior", Role.BEZ_KONTA)
DOM2 = Member("dom2", Role.DOMOWNIK)
HOUSE = [DOM1, KOORD, SENIOR, DOM2]  # OSOBA_1..4


def letter(**fields):
    return {
        "status": "verdict",
        "state": "open",
        "uploaded_by": "koord",
        "addressee": "dom1",
        "owner": "dom1",
        "private": True,
        "deadline": {"date": "2026-10-23", "basis": "DELIVERY", "confirmed": False},
    } | fields


# View matrix: role x relation x private


@pytest.mark.parametrize(
    "fields, user, expected",
    [
        # private letter of dom1, uploaded by dom1
        ({"uploaded_by": "dom1"}, DOM1, View.FULL),
        ({"uploaded_by": "dom1"}, KOORD, View.METADATA),
        ({"uploaded_by": "dom1"}, DOM2, View.NONE),
        # the coordinator uploaded it: uploader sees everything
        ({}, KOORD, View.FULL),
        # not private
        ({"uploaded_by": "dom1", "private": False}, KOORD, View.FULL),
        ({"uploaded_by": "dom1", "private": False}, DOM2, View.NONE),
        # forwarded to dom2: the new owner sees the content
        ({"uploaded_by": "dom1", "owner": "dom2"}, DOM2, View.FULL),
        # letter for someone without an account: coordinator and uploader
        ({"uploaded_by": "dom2", "addressee": "senior", "owner": "koord", "private": False}, KOORD, View.FULL),
        ({"uploaded_by": "dom2", "addressee": "senior", "owner": "koord", "private": False}, DOM2, View.FULL),
        ({"uploaded_by": "dom2", "addressee": "senior", "owner": "koord", "private": False}, DOM1, View.NONE),
        # nobody without an account sees anything
        ({"addressee": "senior"}, SENIOR, View.NONE),
        # still processing: uploader and coordinator
        ({"status": "received", "addressee": None, "owner": None, "uploaded_by": "dom2", "private": False}, DOM2, View.FULL),
        ({"status": "received", "addressee": None, "owner": None, "uploaded_by": "dom2", "private": False}, KOORD, View.FULL),
        ({"status": "received", "addressee": None, "owner": None, "uploaded_by": "dom2", "private": False}, DOM1, View.NONE),
        ({"status": "received", "addressee": None, "owner": None, "uploaded_by": "dom2", "upload_private": True, "private": True}, KOORD, View.METADATA),
    ],
)  # fmt: skip
def test_view_matrix(fields, user, expected):
    assert view_level(letter(**fields), user) == expected


# Actions


@pytest.mark.parametrize(
    "fields, user, expected",
    [
        ({}, DOM1, True),  # addressee and owner
        ({}, KOORD, True),  # uploader
        ({"uploaded_by": "dom1"}, KOORD, False),  # private: metadata only
        ({"uploaded_by": "dom1"}, DOM2, False),
        ({"state": "closed"}, DOM1, False),
        ({"status": "masked"}, KOORD, False),  # not processed yet
        ({"status": "failed"}, KOORD, True),
    ],
)
def test_handle_and_forward(fields, user, expected):
    assert can_act(letter(**fields), user) is expected


@pytest.mark.parametrize(
    "fields, user, expected",
    [
        ({}, DOM1, True),  # owner
        ({"uploaded_by": "dom1"}, KOORD, True),  # coordinator, also on a private letter
        ({"owner": "dom2"}, DOM1, False),  # addressee, no longer owner
        ({}, DOM2, False),
        ({"deadline": None}, DOM1, False),
        ({"status": "received"}, KOORD, False),
    ],
)
def test_confirm_deadline(fields, user, expected):
    assert can_confirm_deadline(letter(**fields), user) is expected


@pytest.mark.parametrize(
    "fields, user, expected",
    [
        ({}, DOM1, True),  # owner
        ({"private": False, "uploaded_by": "dom1"}, KOORD, True),
        ({"uploaded_by": "dom1"}, KOORD, False),  # private: deadline only
        ({}, DOM2, False),
        ({"status": "ocr_done"}, DOM1, False),
    ],
)
def test_close_and_reopen(fields, user, expected):
    assert can_close(letter(**fields), user) is expected


@pytest.mark.parametrize(
    "fields, user, expected",
    [
        ({}, DOM1, True),  # addressee
        ({"uploaded_by": "dom2", "addressee": "senior"}, DOM2, True),  # uploader
        ({"uploaded_by": "dom1"}, KOORD, False),
        ({"private": False}, DOM1, False),  # already visible
    ],
)
def test_reveal(fields, user, expected):
    assert can_reveal(letter(**fields), user) is expected


# „Przekaż” (D17)


def test_forward_targets_have_accounts_and_exclude_the_user():
    assert [m.id for m in forward_targets(HOUSE, DOM1)] == ["koord", "dom2"]


def test_suggestion_from_the_deciding_rule():
    rules = [Rule("R1", "Pisma z uczelni przekazujemy OSOBA_4.")]
    suggestion = forward_suggestion(letter(analysis={"rule_id": "R1"}), HOUSE, rules, DOM1)
    assert suggestion.id == "dom2"


def test_suggestion_falls_back_to_the_coordinator():
    rules = [Rule("R1", "Pisma od seniora: OSOBA_3.")]  # no account
    assert forward_suggestion(letter(analysis={"rule_id": "R1"}), HOUSE, rules, DOM1).id == "koord"
    assert forward_suggestion(letter(analysis=None), HOUSE, rules, DOM1).id == "koord"


def test_no_suggestion_of_oneself():
    rules = [Rule("R1", "Rachunki: OSOBA_2.")]
    assert forward_suggestion(letter(analysis={"rule_id": "R1"}), HOUSE, rules, KOORD) is None
