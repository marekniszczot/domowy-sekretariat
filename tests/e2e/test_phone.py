import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import expect

from tests.e2e.conftest import ALA, OLEK, add_letter, iso

pytestmark = pytest.mark.e2e

STATES = {
    "ok": {"verdict": "NONE", "deadline": None},
    "todo": {},
    "unsure": {"verdict": "FORWARD", "reasons": ["LOW_CONFIDENCE"], "deadline": None},
    "urgent": {"verdict": "FORWARD", "reasons": ["ESCALATION"]},
}


def assert_accessible(page):
    """No serious or critical axe findings (DR-14: contrast, labels, roles)."""
    results = Axe().run(page)
    problems = [
        f"{v['id']} ({v['impact']}): {v['help']} – {[n['target'] for n in v['nodes']][:3]}"
        for v in results.response["violations"]
        if v["impact"] in {"serious", "critical"}
    ]
    assert not problems, "\n".join(problems)


def test_sign_in_page(page, server):
    page.goto(server.url)
    expect(page.get_by_role("heading", name="Domowy Sekretariat")).to_be_visible()
    assert_accessible(page)


@pytest.mark.parametrize("state", STATES)
def test_verdict_card_in_each_state(sign_in, server, store, state):
    letter_id = add_letter(store, **STATES[state])
    page = sign_in(ALA)
    page.goto(f"{server.url}/pisma/{letter_id}")
    stamp = page.locator(f".stamp.{state}")
    expect(stamp).to_be_visible()
    expect(stamp).to_have_attribute("role", "img")
    page.wait_for_timeout(1000)  # the stamp lands on the first look
    assert_accessible(page)


@pytest.mark.parametrize(
    "path, member",
    [("/", ALA), ("/dodaj", ALA), ("/wszystkie", OLEK), ("/dom", OLEK)],
)
def test_screens(sign_in, server, store, path, member):
    add_letter(store)
    add_letter(store, private=True, deadline={"date": iso(2), "basis": "STATED", "confirmed": True})
    page = sign_in(member)
    page.goto(server.url + path)
    expect(page.locator("h1")).to_be_visible()
    assert_accessible(page)


def test_touch_targets_are_at_least_48_px(sign_in, server, store):
    letter_id = add_letter(store)
    page = sign_in(ALA)
    for path in ("/", f"/pisma/{letter_id}", "/dodaj"):
        page.goto(server.url + path)
        targets = page.locator(".tab, .action-bar .btn, .row, .chip span, .back, .deadline, .btn")
        for index in range(targets.count()):
            box = targets.nth(index).bounding_box()
            if box:  # hidden elements have no box
                assert box["height"] >= 48, (path, targets.nth(index).inner_text(), box)


def test_upload_shows_steps_then_the_card(sign_in, server, store):
    page = sign_in(ALA)
    page.goto(f"{server.url}/dodaj")
    page.set_input_files(
        "#camera", files=[{"name": "p1.jpg", "mimeType": "image/jpeg", "buffer": b"\xff\xd8 one"}]
    )
    expect(page.locator(".thumb.page")).to_have_count(1)
    page.get_by_role("button", name="Gotowe, przeanalizuj").click()
    expect(page.get_by_role("heading", name="Czytam pismo")).to_be_visible()
    letter_id = page.url.rsplit("/", 1)[1]
    store.update_letter(letter_id, add_and_take(store))  # the pipeline finishes
    expect(page.locator(".stamp")).to_be_visible(timeout=5000)
    expect(page).to_have_url(re.compile(f"/pisma/{letter_id}$"))


def add_and_take(store) -> dict:
    """The fields the pipeline writes, taken from a finished sample letter."""
    sample = store.get_letter(add_letter(store))
    return {key: value for key, value in sample.items() if key not in {"pages", "uploaded_by"}}


def test_take_done_and_undo(sign_in, server, store):
    letter_id = add_letter(store)
    page = sign_in(ALA)
    page.goto(f"{server.url}/pisma/{letter_id}")
    page.get_by_role("button", name="Zajmę się tym").click()
    expect(page.get_by_role("status")).to_contain_text("Zajmiesz się tym pismem.")
    page.get_by_role("button", name="Zrobione").click()
    expect(page.get_by_role("status")).to_contain_text("Oznaczono jako zrobione.")
    page.get_by_role("status").get_by_role("button", name="Cofnij").click()
    expect(page.get_by_role("heading", name="Moje pisma")).to_be_visible()
    assert store.get_letter(letter_id)["state"] == "open"


def test_forward_sheet(sign_in, server, store):
    letter_id = add_letter(store, owner="olek", addressee="olek", uploaded_by="olek")
    page = sign_in(OLEK)
    page.goto(f"{server.url}/pisma/{letter_id}")
    page.locator(".action-bar").get_by_role("button", name="Przekaż").click()
    sheet = page.locator("#forward-sheet")
    expect(sheet).to_be_visible()
    assert_accessible(page)
    sheet.get_by_role("button", name=re.compile("^Ala")).click()
    expect(page.get_by_role("status")).to_contain_text("Przekazano: Ala.")
    assert store.get_letter(letter_id)["owner"] == "ala"


def test_deadline_sheet_confirms_a_corrected_date(sign_in, server, store):
    letter_id = add_letter(store)
    page = sign_in(ALA)
    page.goto(f"{server.url}/pisma/{letter_id}")
    page.get_by_role("button", name=re.compile("Sprawdź")).click()
    sheet = page.locator("#deadline-sheet")
    expect(sheet.locator("mark")).to_have_text("do dnia 20.10.")
    sheet.locator("input[type=date]").fill(iso(11))
    expect(sheet.get_by_role("button", name="Zapisz tę datę")).to_be_visible()
    sheet.get_by_role("button", name="Zapisz tę datę").click()
    expect(page.get_by_role("status")).to_contain_text("Termin zatwierdzony.")
    assert store.get_letter(letter_id)["deadline"]["date"] == iso(11)


def test_dark_mode_keeps_contrast(sign_in, server, store):
    """Dark tokens from DESIGN.md: every state stamp and the list."""
    ids = [add_letter(store, **fields) for fields in STATES.values()]
    page = sign_in(ALA)
    page.emulate_media(color_scheme="dark")
    for letter_id in ids:
        page.goto(f"{server.url}/pisma/{letter_id}")
        page.wait_for_timeout(1000)
        assert_accessible(page)
    page.goto(server.url)
    assert_accessible(page)
