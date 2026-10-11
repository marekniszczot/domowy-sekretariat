from datetime import date, timedelta

import pytest

from sekretariat.access import View
from sekretariat.blobs import MemoryBlobs
from sekretariat.household import Member, Role
from sekretariat.letters import (
    MAX_PAGES,
    Forbidden,
    InvalidUpload,
    Letters,
    NeedsConfirmation,
    NotFound,
)
from sekretariat.store import MemoryStore, now

DOM1 = Member("dom1", Role.DOMOWNIK)
KOORD = Member("koord", Role.KOORDYNATOR)
SENIOR = Member("senior", Role.BEZ_KONTA)
DOM2 = Member("dom2", Role.DOMOWNIK)
HOUSE = [DOM1, KOORD, SENIOR, DOM2]
JPEG = (b"\xff\xd8 page", "image/jpeg")


@pytest.fixture
def service():
    queued = []
    letters = Letters(MemoryStore(), MemoryBlobs(), queued.append, HOUSE)
    letters.queued = queued
    return letters


def processed(service, **fields):
    """A letter as the pipeline leaves it: dom1's private letter uploaded by dom1."""
    return service.store.create_letter(
        {
            "status": "verdict",
            "state": "open",
            "uploaded_by": "dom1",
            "addressee": "dom1",
            "owner": "dom1",
            "private": True,
            "verdict": "SELF",
            "masked_text": "treść",
            "analysis": {"sender_type": "BANK", "rule_id": "R1"},
            "deadline": {"date": "2026-10-23", "basis": "DELIVERY", "confirmed": False},
        }
        | fields
    )


# Upload


def test_upload_stores_pages_and_enqueues(service):
    result = service.upload(
        DOM1, [JPEG, (b"%PDF-1.7", "application/pdf")], date(2026, 10, 9), False
    )

    assert not result.duplicate
    assert service.queued == [result.letter_id]
    letter = service.store.get_letter(result.letter_id)
    assert letter["status"] == "received"
    assert letter["uploaded_by"] == "dom1"
    assert letter["delivery_date"] == "2026-10-09"
    assert [p["mime"] for p in letter["pages"]] == ["image/jpeg", "application/pdf"]
    assert letter["pages"][0]["path"].endswith("/p1.jpg")
    assert service.blobs.get(letter["pages"][1]["path"]) == (b"%PDF-1.7", "application/pdf")


def test_duplicate_upload_returns_the_existing_letter(service):
    first = service.upload(DOM1, [JPEG], date(2026, 10, 9), False)
    second = service.upload(DOM1, [JPEG], date(2026, 10, 10), False)
    assert second.duplicate and second.letter_id == first.letter_id
    assert service.queued == [first.letter_id, first.letter_id]  # still received: re-enqueued


def test_duplicate_of_an_invisible_letter_is_not_revealed(service):
    first = service.upload(DOM1, [JPEG], date(2026, 10, 9), True)
    service.store.update_letter(
        first.letter_id, {"status": "verdict", "addressee": "dom1", "owner": "dom1"}
    )
    second = service.upload(DOM2, [JPEG], date(2026, 10, 9), False)
    assert not second.duplicate and second.letter_id != first.letter_id


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [JPEG] * (MAX_PAGES + 1),
        [(b"GIF89a", "image/gif")],
        [(b"", "image/jpeg")],
    ],
)
def test_invalid_uploads(service, pages):
    with pytest.raises(InvalidUpload):
        service.upload(DOM1, pages, date(2026, 10, 9), False)


def test_member_without_account_cannot_upload(service):
    with pytest.raises(Forbidden):
        service.upload(SENIOR, [JPEG], date(2026, 10, 9), False)


# Reading


def test_private_letter_is_metadata_for_the_coordinator(service):
    letter_id = processed(service)
    letter, level = service.get(letter_id, KOORD)
    assert level == View.METADATA
    assert letter["sender_type"] == "BANK"
    assert "masked_text" not in letter and "verdict" not in letter and "analysis" not in letter


def test_invisible_letter_is_not_found(service):
    letter_id = processed(service)
    with pytest.raises(NotFound):
        service.get(letter_id, DOM2)
    with pytest.raises(NotFound):
        service.get("missing", DOM1)


def test_my_letters_are_owned_or_my_uploads_in_progress(service):
    mine = processed(service)
    processed(service, owner="koord", addressee="koord", uploaded_by="koord")
    uploading = service.store.create_letter({"status": "ocr_done", "uploaded_by": "dom1"})
    assert {letter["id"] for letter in service.mine(DOM1)} == {mine, uploading}


def test_household_letters_for_the_coordinator_only(service):
    processed(service)
    processed(service, private=False)
    levels = [level for _, level in service.household_letters(KOORD)]
    assert sorted(levels) == [View.METADATA, View.FULL]
    with pytest.raises(Forbidden):
        service.household_letters(DOM1)


# Actions and undo


def test_handle_records_event_and_owner(service):
    letter_id = processed(service, owner="koord", private=False)
    service.handle(letter_id, DOM1)
    assert service.store.get_letter(letter_id)["owner"] == "dom1"
    event = service.store.events(letter_id)[-1]
    assert (event["cause"], event["actor"], event["previous"], event["owner"]) == (
        "HANDLE",
        "dom1",
        "koord",
        "dom1",
    )


def test_forwarding_a_private_letter_needs_confirmation(service):
    letter_id = processed(service)
    with pytest.raises(NeedsConfirmation):
        service.forward(letter_id, DOM1, "dom2")
    service.forward(letter_id, DOM1, "dom2", confirmed=True)
    assert service.store.get_letter(letter_id)["owner"] == "dom2"
    _, level = service.get(letter_id, DOM2)
    assert level == View.FULL


def test_forward_to_someone_without_an_account_fails(service):
    letter_id = processed(service, private=False)
    with pytest.raises(ValueError):
        service.forward(letter_id, DOM1, "senior")


def test_coordinator_cannot_act_on_private_content(service):
    letter_id = processed(service)
    with pytest.raises(Forbidden):
        service.handle(letter_id, KOORD)
    with pytest.raises(Forbidden):
        service.done(letter_id, KOORD)
    service.confirm_deadline(letter_id, KOORD)  # the deadline is allowed (D16)
    assert service.store.get_letter(letter_id)["deadline"]["confirmed"] is True


def test_confirm_deadline_with_a_corrected_date(service):
    letter_id = processed(service)
    service.confirm_deadline(letter_id, DOM1, date(2026, 10, 20))
    assert service.store.get_letter(letter_id)["deadline"] == {
        "date": "2026-10-20",
        "basis": "DELIVERY",
        "confirmed": True,
    }


def test_confirming_a_deadline_checks_reminders(service):
    reminded = []
    service.remind = reminded.append
    letter_id = processed(service)
    service.confirm_deadline(letter_id, DOM1, date(2026, 10, 20))
    assert reminded == [letter_id]


def test_forwarding_assigns_and_notifies_the_new_owner(service):
    notified = []
    service.notify = notified.append
    letter_id = processed(service, private=False, owner="koord")
    service.forward(letter_id, KOORD, "dom2")
    assigned = service.store.get_letter(letter_id)["assigned"]
    assert (assigned["to"], assigned["by"], assigned["cause"]) == ("dom2", "koord", "FORWARD")
    assert notified == ["dom2"]


def test_forwarding_to_oneself_and_taking_notify_nobody(service):
    notified = []
    service.notify = notified.append
    letter_id = processed(service, private=False, owner="koord")
    service.forward(letter_id, KOORD, "koord")
    service.handle(letter_id, KOORD)
    assert notified == []


def test_done_reopen_reveal(service):
    letter_id = processed(service)
    service.done(letter_id, DOM1)
    assert service.store.get_letter(letter_id)["state"] == "closed"
    service.reopen(letter_id, DOM1)
    assert service.store.get_letter(letter_id)["state"] == "open"
    service.reveal(letter_id, DOM1)
    assert service.get(letter_id, KOORD)[1] == View.FULL


@pytest.mark.parametrize(
    "action",
    [
        lambda s, i: s.handle(i, DOM2),
        lambda s, i: s.forward(i, DOM2, "koord"),
        lambda s, i: s.done(i, DOM2),
        lambda s, i: s.reveal(i, DOM2),
        lambda s, i: s.confirm_deadline(i, DOM2),
    ],
)
def test_strangers_get_not_found(service, action):
    letter_id = processed(service)
    with pytest.raises(NotFound):
        action(service, letter_id)


@pytest.mark.parametrize(
    "action, field, before",
    [
        (lambda s, i: s.forward(i, DOM1, "koord", confirmed=True), "owner", "dom1"),
        (lambda s, i: s.handle(i, DOM1), "taken", None),
        (lambda s, i: s.done(i, DOM1), "state", "open"),
        (lambda s, i: s.reveal(i, DOM1), "private", True),
        (lambda s, i: s.confirm_deadline(i, DOM1), "deadline", {"date": "2026-10-23", "basis": "DELIVERY", "confirmed": False}),
    ],
)  # fmt: skip
def test_undo_restores_the_previous_state(service, action, field, before):
    letter_id = processed(service)
    action(service, letter_id)
    assert service.store.get_letter(letter_id)[field] != before
    service.undo(letter_id, DOM1)
    assert service.store.get_letter(letter_id)[field] == before
    assert service.store.events(letter_id)[-1]["cause"] == "UNDO"
    with pytest.raises(Forbidden):
        service.undo(letter_id, DOM1)  # only once


def test_undo_by_someone_else_or_too_late(service):
    letter_id = processed(service, private=False)
    service.done(letter_id, DOM1)
    with pytest.raises(Forbidden):
        service.undo(letter_id, KOORD)
    last = service.store.get_letter(letter_id)["last_action"]
    service.store.update_letter(
        letter_id, {"last_action": last | {"at": now() - timedelta(minutes=5)}}
    )
    with pytest.raises(Forbidden):
        service.undo(letter_id, DOM1)


# Page photos and first look


def test_page_photo_needs_full_view(service):
    service.blobs.put("uploads/x/p1.jpg", *JPEG)
    letter_id = processed(service, pages=[{"path": "uploads/x/p1.jpg", "mime": "image/jpeg"}])
    assert service.page(letter_id, DOM1, 1) == JPEG
    with pytest.raises(Forbidden):
        service.page(letter_id, KOORD, 1)  # private: metadata only
    with pytest.raises(NotFound):
        service.page(letter_id, DOM2, 1)
    with pytest.raises(NotFound):
        service.page(letter_id, DOM1, 2)


def test_page_deleted_by_retention_is_not_found(service):
    letter_id = processed(service, pages=[{"path": "uploads/gone/p1.jpg", "mime": "image/jpeg"}])
    with pytest.raises(NotFound):
        service.page(letter_id, DOM1, 1)


def test_first_look_is_reported_once_per_member(service):
    letter_id = processed(service, private=False)
    assert service.mark_seen(letter_id, DOM1) is True
    assert service.mark_seen(letter_id, DOM1) is False
    assert service.mark_seen(letter_id, KOORD) is True
    assert service.store.get_letter(letter_id)["seen_by"] == ["dom1", "koord"]


def test_letter_in_progress_is_not_marked_seen(service):
    letter_id = processed(service, status="masked")
    assert service.mark_seen(letter_id, DOM1) is False
    assert "seen_by" not in service.store.get_letter(letter_id)


def test_taking_a_letter_and_forwarding_it_again(service):
    letter_id = processed(service, private=False)
    service.handle(letter_id, DOM1)
    assert service.store.get_letter(letter_id)["taken"] is True
    service.forward(letter_id, DOM1, "koord")
    letter = service.store.get_letter(letter_id)
    assert (letter["owner"], letter["taken"]) == ("koord", False)


def test_recent_action_is_only_the_users_own_and_fresh(service):
    letter_id = processed(service, private=False)
    assert service.recent_action(letter_id, DOM1) is None
    service.forward(letter_id, DOM1, "koord")
    assert service.recent_action(letter_id, DOM1) == {"cause": "FORWARD", "owner": "koord"}
    assert service.recent_action(letter_id, KOORD) is None
    assert service.recent_action("nope", DOM1) is None


def test_memory_store_rules_and_escalation():
    from sekretariat.store import MemoryStore

    store = MemoryStore()
    assert store.add_rule("a") == "R1" and store.add_rule("b") == "R2"
    store.delete_rule("R2")
    assert store.add_rule("c") == "R3"
    assert [r.id for r in store.rules()] == ["R1", "R3"]
    store.set_escalation(["komorni"])
    assert store.escalation() == ("komorni",)
