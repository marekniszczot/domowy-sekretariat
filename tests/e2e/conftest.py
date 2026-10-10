"""Phone-sized browser tests (DT2, DR-14): WebKit as an iPhone 13, the app on a live
server with memory storage. Needs `uv run playwright install webkit` once.

Run: uv run pytest -m e2e
"""

import socket
import threading
import time
from datetime import timedelta

import pytest
import uvicorn

from sekretariat.api.app import AppConfig, create_app
from sekretariat.auth import SESSION_COOKIE, Sessions
from sekretariat.blobs import MemoryBlobs
from sekretariat.household import Member, Role
from sekretariat.letters import Letters
from sekretariat.rules import Rule
from sekretariat.store import MemoryStore
from sekretariat.web.pages import today

ALA = Member("ala", Role.DOMOWNIK, ("Ala",), emails=("ala@example.com",))
OLEK = Member("olek", Role.KOORDYNATOR, ("Olek",), emails=("olek@example.com",))
ULA = Member("ula", Role.DOMOWNIK, ("Ula",), emails=("ula@example.com",))
HOUSE = [ALA, OLEK, ULA]
SESSIONS = Sessions("e2e")


class Server:
    def __init__(self):
        self.store = MemoryStore()
        self.blobs = MemoryBlobs()
        app = create_app(
            AppConfig(
                letters=Letters(self.store, self.blobs, lambda _: None, HOUSE),
                household=HOUSE,
                sessions=SESSIONS,
                google_client_id="e2e",
                verify_token=lambda token, audience: {},
                tasks_audience="",
                tasks_service_account="",
                process=lambda letter_id, attempt: "verdict",
                secure_cookies=False,
            )
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )

    def __enter__(self):
        threading.Thread(target=self._server.run, daemon=True).start()
        while not self._server.started:
            time.sleep(0.05)
        return self

    def __exit__(self, *_):
        self._server.should_exit = True


@pytest.fixture(scope="session")
def server():
    with Server() as running:
        yield running


@pytest.fixture
def store(server):
    server.store.letters.clear()
    server.store._rules = [Rule("R1", "Rachunki ogarnia OSOBA_1.", "Rachunki ogarnia Ala.")]
    return server.store


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, playwright):
    return {**browser_context_args, **playwright.devices["iPhone 13"], "locale": "pl-PL"}


@pytest.fixture
def sign_in(page, server):
    def as_member(member: Member):
        page.context.add_cookies(
            [{"name": SESSION_COOKIE, "value": SESSIONS.issue(member), "url": server.url}]
        )
        return page

    return as_member


def iso(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


RAW = "Prosimy o zapłatę 120 zł do dnia 20.10. Brak zapłaty oznacza odsetki."


def add_letter(store, **fields) -> str:
    deadline = RAW.index("do dnia")
    return store.create_letter(
        {
            "status": "verdict",
            "state": "open",
            "uploaded_by": "ala",
            "addressee": "ala",
            "owner": "ala",
            "private": False,
            "verdict": "SELF",
            "reasons": [],
            "raw_text": RAW,
            "delivery_date": iso(-1),
            "analysis": {
                "sender_type": "ENERGIA",
                "summary_plain_pl": "Rachunek za prąd.",
                "required_action": "Opłać rachunek.",
                "rule_id": "R1",
                "confidence": 0.95,
            },
            "quote_spans_raw": {"deadline_quote": [deadline, deadline + 14]},
            "deadline": {"date": iso(9), "basis": "STATED", "confirmed": False},
        }
        | fields
    )
