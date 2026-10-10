from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from sekretariat.api.app import AppConfig, create_app
from sekretariat.auth import SESSION_COOKIE, Sessions
from sekretariat.blobs import MemoryBlobs
from sekretariat.household import Member, Role
from sekretariat.letters import Letters
from sekretariat.rules import Rule
from sekretariat.store import MemoryStore
from sekretariat.web.pages import today

DOM1 = Member("dom1", Role.DOMOWNIK, ("Ala",), emails=("dom1@example.com",))
KOORD = Member("koord", Role.KOORDYNATOR, ("Olek",), emails=("koord@example.com",))
DOM2 = Member("dom2", Role.DOMOWNIK, ("Ula",), emails=("dom2@example.com",))
HOUSE = [DOM1, KOORD, DOM2]
JPEG = (b"\xff\xd8 page", "image/jpeg")


@pytest.fixture
def store():
    return MemoryStore(rules=[Rule("R1", "Rachunki ogarnia OSOBA_1.")])


@pytest.fixture
def app(store):
    blobs = MemoryBlobs()
    blobs.put("uploads/a/p1.jpg", *JPEG)
    config = AppConfig(
        letters=Letters(store, blobs, lambda _: None, HOUSE),
        household=HOUSE,
        sessions=Sessions("secret"),
        google_client_id="client",
        verify_token=lambda token, audience: {},
        tasks_audience="",
        tasks_service_account="",
        process=lambda letter_id, attempt: "verdict",
        secure_cookies=False,
    )
    return create_app(config)


def as_member(app, member: Member | None) -> TestClient:
    http = TestClient(app, follow_redirects=False, headers={"Origin": "http://testserver"})
    if member:
        http.cookies.set(SESSION_COOKIE, Sessions("secret").issue(member))
    return http


def iso(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


RAW = "Prosimy o zapłatę 120 zł do dnia 20.10. Brak zapłaty oznacza odsetki."


def verdict_letter(store, **fields) -> str:
    deadline = RAW.index("do dnia")
    return store.create_letter(
        {
            "status": "verdict",
            "state": "open",
            "uploaded_by": "dom1",
            "addressee": "dom1",
            "owner": "dom1",
            "private": False,
            "verdict": "SELF",
            "reasons": [],
            "raw_text": RAW,
            "delivery_date": iso(-1),
            "pages": [{"path": "uploads/a/p1.jpg", "mime": "image/jpeg"}],
            "analysis": {
                "sender_type": "ENERGIA",
                "summary_plain_pl": "Rachunek za prąd dla OSOBA_1, świadek INNA_1.",
                "required_action": "Opłać rachunek.",
                "rule_id": "R1",
                "confidence": 0.95,
            },
            "quote_spans_raw": {"deadline_quote": [deadline, deadline + len("do dnia 20.10.")]},
            "deadline": {"date": iso(9), "basis": "STATED", "confirmed": True},
        }
        | fields
    )


# Moje pisma


def test_my_letters_are_grouped_with_state_words(app, store):
    verdict_letter(store)
    verdict_letter(store, deadline={"date": iso(-2), "basis": "STATED", "confirmed": True})
    verdict_letter(store, owner="koord")  # someone else's
    page = as_member(app, DOM1).get("/").text
    assert page.index("Po terminie") < page.index("Później i bez terminu")
    assert "2 dni po" in page and "Pilne" in page
    assert page.count('class="row"') == 2
    assert page.count('aria-label="nowe"') == 2


def test_closed_letters_go_to_done(app, store):
    verdict_letter(store, state="closed")
    page = as_member(app, DOM1).get("/").text
    assert "Zrobione" in page and "Nic na Ciebie nie czeka" not in page


# Verdict card


def test_card_in_words_with_names_and_no_codes(app, store):
    letter_id = verdict_letter(store)
    page = as_member(app, DOM1).get(f"/pisma/{letter_id}").text
    assert "Opłać rachunek" in page and "Do zrobienia" in page
    assert "za 9 dni · do " in page and "przyszło wczoraj" in page
    assert "Rachunek za prąd dla Ala, świadek inna osoba." in page
    assert "Dlaczego Ala" in page and "„Rachunki ogarnia Ala.”" in page
    assert "<mark>do dnia 20.10.</mark>" in page
    for code in ["OSOBA_", "INNA_", "SELF", "R1", "0.95"]:
        assert code not in page


def test_stamp_lands_only_on_the_first_look(app, store):
    letter_id = verdict_letter(store)
    http = as_member(app, DOM1)
    assert "verdict-stamp todo land" in http.get(f"/pisma/{letter_id}").text
    assert "verdict-stamp todo land" not in http.get(f"/pisma/{letter_id}").text
    assert 'aria-label="nowe"' not in http.get("/").text


def test_unsure_card_says_why(app, store):
    letter_id = verdict_letter(store, verdict="FORWARD", reasons=["QUOTE_NOT_FOUND"])
    page = as_member(app, DOM1).get(f"/pisma/{letter_id}").text
    assert "Nie mam pewności" in page and "Przekaż dalej" in page
    assert "Powód: cytat nie zgadza się z pismem." in page


def test_unreadable_letter_asks_for_a_new_photo(app, store):
    letter_id = store.create_letter(
        {"status": "unreadable", "uploaded_by": "dom1", "owner": "dom1", "state": "open"}
    )
    page = as_member(app, DOM1).get(f"/pisma/{letter_id}").text
    assert "Nie mogę odczytać" in page


def test_private_letter_shows_only_metadata_to_the_coordinator(app, store):
    letter_id = verdict_letter(store, private=True)
    page = as_member(app, KOORD).get(f"/pisma/{letter_id}").text
    assert "To pismo jest prywatne" in page and "Dostawca energii" in page
    assert "Rachunek za prąd" not in page and "Opłać" not in page
    assert "seen_by" not in store.get_letter(letter_id)


def test_invisible_or_missing_letter_is_not_found(app, store):
    letter_id = verdict_letter(store)
    assert as_member(app, DOM2).get(f"/pisma/{letter_id}").status_code == 404
    assert as_member(app, DOM1).get("/pisma/nope").status_code == 404


def test_signed_out_letter_link_shows_sign_in(app, store):
    letter_id = verdict_letter(store)
    page = as_member(app, None).get(f"/pisma/{letter_id}").text
    assert "g_id_signin" in page and "Opłać" not in page


# Processing


def test_processing_letter_shows_steps_and_polls(app, store):
    letter_id = store.create_letter({"status": "ocr_done", "uploaded_by": "dom1"})
    http = as_member(app, DOM1)
    page = http.get(f"/pisma/{letter_id}").text
    assert f'hx-get="/pisma/{letter_id}/kroki"' in page
    assert page.index("Czytam pismo</span>") < page.index("Ukrywam dane osobowe…")
    store.update_letter(letter_id, {"status": "masked"})
    assert "Sprawdzam Wasze zasady…" in http.get(f"/pisma/{letter_id}/kroki").text


def test_finished_processing_redirects_to_the_card(app, store):
    letter_id = verdict_letter(store)
    response = as_member(app, DOM1).get(f"/pisma/{letter_id}/kroki")
    assert response.headers["HX-Redirect"] == f"/pisma/{letter_id}"


# Page photos


def test_page_photo_follows_the_access_rules(app, store):
    letter_id = verdict_letter(store, private=True)
    response = as_member(app, DOM1).get(f"/pisma/{letter_id}/strona/1")
    assert response.status_code == 200 and response.content == JPEG[0]
    assert response.headers["content-type"] == "image/jpeg"
    assert "private" in response.headers["cache-control"]
    assert as_member(app, KOORD).get(f"/pisma/{letter_id}/strona/1").status_code == 403
    assert as_member(app, DOM2).get(f"/pisma/{letter_id}/strona/1").status_code == 404
    assert as_member(app, None).get(f"/pisma/{letter_id}/strona/1").status_code == 401
