import pytest

from sekretariat.blobs import MemoryBlobs
from sekretariat.household import Member, Role
from sekretariat.llm import LetterAnalysis, LlmFailure
from sekretariat.mask import PERSON, Finding
from sekretariat.pipeline import MAX_ATTEMPTS, Services, process
from sekretariat.rules import Rule
from sekretariat.store import MemoryStore

# Synthetic letter. OSOBA_1 = dom1 (domownik), OSOBA_2 = koord, OSOBA_3 = senior.
HOUSEHOLD = [
    Member("dom1", Role.DOMOWNIK, ("Jan", "Jana"), ("Testowy", "Testowego"), ("j@example.com",)),
    Member("koord", Role.KOORDYNATOR, ("Piotr",), ("Testowy",), ("p@example.com",)),
    Member("senior", Role.BEZ_KONTA, ("Zofia",), ("Wzorcowa",)),
]
RULES = [Rule("R1", "Rachunki za telefon do 300 zł opłaca OSOBA_1.")]
LETTER = (
    "Warszawa, 2 października 2026 r.\n"
    "Szanowny Pan Jan Testowy\n"
    "Prosimy o zapłatę 89,00 zł za telefon w terminie 14 dni od dnia doręczenia.\n"
    "Telekom S.A."
)


def analysis(**overrides):
    fields = {
        "sender_type": "TELEKOMUNIKACJA",
        "addressee": "OSOBA_1",
        "summary_plain_pl": "Rachunek za telefon.",
        "required_action": "Zapłać 89 zł.",
        "verdict": "SELF",
        "rule_id": "R1",
        "rule_trigger_quote": "Prosimy o zapłatę 89,00 zł za telefon",
        "deadline_type": "RELATIVE",
        "deadline_date": None,
        "deadline_relative_amount": 14,
        "deadline_relative_unit": "DAYS",
        "deadline_quote": "w terminie 14 dni od dnia doręczenia",
        "consequence_quote": None,
        "letter_date": "2026-10-02",
        "letter_date_quote": "2 października 2026 r.",
        "confidence": 0.95,
    }
    return LetterAnalysis(**(fields | overrides))


class Fake:
    """Services with call counters and scriptable failures."""

    def __init__(self, text=LETTER, outcome=None):
        self.store = MemoryStore(rules=RULES)
        self.blobs = MemoryBlobs()
        self.text = text
        self.outcome = outcome or analysis()
        self.calls = {"ocr": 0, "inspect": 0, "analyze": 0}
        self.fail = set()  # stage names that raise once
        self.services = Services(
            self.store, self.blobs, self.ocr, self.inspect, self.analyze, HOUSEHOLD
        )

    def _maybe_fail(self, stage):
        self.calls[stage] += 1
        if stage in self.fail:
            self.fail.discard(stage)
            raise ConnectionError(stage)

    def ocr(self, pages):
        self._maybe_fail("ocr")
        assert pages == [(b"page-1", "image/jpeg"), (b"page-2", "image/jpeg")]
        return self.text

    def inspect(self, text):
        self._maybe_fail("inspect")
        start = text.find("Szanowny Pan") + len("Szanowny ")
        return [Finding(start, start + len("Pan Jan Testowy"), PERSON)] if start > 8 else []

    def analyze(self, masked_text, rules):
        self._maybe_fail("analyze")
        assert "Testowy" not in masked_text and "Jan" not in masked_text
        assert rules == RULES
        return self.outcome

    def upload(self, **fields):
        for name in ("p1.jpg", "p2.jpg"):
            self.blobs.put(f"letters/x/{name}", f"page-{name[1]}".encode(), "image/jpeg")
        return self.store.create_letter(
            {
                "status": "received",
                "uploaded_by": "koord",
                "delivery_date": "2026-10-09",
                "upload_private": False,
                "pages": [
                    {"path": "letters/x/p1.jpg", "mime": "image/jpeg"},
                    {"path": "letters/x/p2.jpg", "mime": "image/jpeg"},
                ],
            }
            | fields
        )


def test_happy_path_saves_everything():
    fake = Fake()
    letter_id = fake.upload()

    assert process(fake.services, letter_id) == "verdict"

    letter = fake.store.get_letter(letter_id)
    assert letter["masked_text"].count("OSOBA_1") == 1
    assert "Testowy" not in letter["masked_text"]
    assert letter["verdict"] == "SELF"
    assert letter["reasons"] == []
    assert letter["addressee"] == "dom1"
    assert letter["owner"] == "dom1"
    assert letter["state"] == "open"
    assert letter["deadline"] == {"date": "2026-10-23", "basis": "DELIVERY", "confirmed": False}
    raw_start, raw_end = letter["quote_spans_raw"]["deadline_quote"]
    assert letter["raw_text"][raw_start:raw_end] == "w terminie 14 dni od dnia doręczenia"
    assert fake.store.events(letter_id)[0] | {"at": None} == {
        "at": None,
        "cause": "INITIAL",
        "owner": "dom1",
        "previous": None,
        "actor": None,
    }


@pytest.mark.parametrize(
    "addressee, upload_private, private",
    [
        ("OSOBA_1", False, True),  # adult member with an account: private by default (DR-5)
        ("OSOBA_2", False, False),  # the coordinator
        ("OSOBA_3", False, False),  # member without an account
        ("INNA_1", False, False),
        ("INNA_1", True, True),  # the uploader marked it private
    ],
)
def test_default_privacy(addressee, upload_private, private):
    fake = Fake(outcome=analysis(addressee=addressee))
    letter_id = fake.upload(upload_private=upload_private)
    process(fake.services, letter_id)
    assert fake.store.get_letter(letter_id)["private"] is private


def test_guard_forward_is_saved_with_reasons():
    fake = Fake(outcome=analysis(rule_trigger_quote="zmyślony cytat"))
    letter_id = fake.upload()
    process(fake.services, letter_id)
    letter = fake.store.get_letter(letter_id)
    assert letter["verdict"] == "FORWARD"
    assert letter["reasons"] == ["QUOTE_NOT_FOUND"]
    assert "rule_trigger_quote" not in letter["quote_spans_raw"]


def test_refusal_is_not_retried():
    fake = Fake(outcome=LlmFailure("refused: SAFETY"))
    letter_id = fake.upload()
    assert process(fake.services, letter_id) == "verdict"
    letter = fake.store.get_letter(letter_id)
    assert (letter["verdict"], letter["reasons"], letter["owner"]) == (
        "FORWARD",
        ["MODEL_FAILED"],
        "koord",
    )
    assert letter["deadline"] is None


def test_model_error_is_retried():
    fake = Fake(outcome=LlmFailure("error: ServiceUnavailable"))
    letter_id = fake.upload()
    with pytest.raises(Exception, match="ServiceUnavailable"):
        process(fake.services, letter_id, attempt=0)
    assert fake.store.get_letter(letter_id)["status"] == "masked"


@pytest.mark.parametrize(
    "stage, status_after_error",
    [("ocr", "received"), ("inspect", "ocr_done"), ("analyze", "masked")],
)
def test_retry_resumes_at_the_failed_stage(stage, status_after_error):
    fake = Fake()
    letter_id = fake.upload()
    fake.fail.add(stage)

    with pytest.raises(ConnectionError):
        process(fake.services, letter_id, attempt=0)
    assert fake.store.get_letter(letter_id)["status"] == status_after_error

    assert process(fake.services, letter_id, attempt=1) == "verdict"
    expected = {"ocr": 1, "inspect": 1, "analyze": 1}
    expected[stage] = 2
    assert fake.calls == expected


def test_duplicate_delivery_does_nothing():
    fake = Fake()
    letter_id = fake.upload()
    process(fake.services, letter_id)
    assert process(fake.services, letter_id) == "verdict"
    assert fake.calls == {"ocr": 1, "inspect": 1, "analyze": 1}
    assert len(fake.store.events(letter_id)) == 1


def test_reminder_check_once_the_verdict_is_saved():
    fake = Fake()
    reminded = []
    fake.services.remind = reminded.append
    letter_id = fake.upload()
    fake.fail.add("analyze")
    with pytest.raises(ConnectionError):
        process(fake.services, letter_id)
    assert reminded == []
    process(fake.services, letter_id)
    process(fake.services, letter_id)  # duplicate delivery
    assert reminded == [letter_id]


def test_last_attempt_fails_to_forward():
    fake = Fake()
    letter_id = fake.upload(upload_private=True)
    fake.fail.add("inspect")

    assert process(fake.services, letter_id, attempt=MAX_ATTEMPTS - 1) == "failed"

    letter = fake.store.get_letter(letter_id)
    assert (letter["verdict"], letter["reasons"], letter["owner"], letter["private"]) == (
        "FORWARD",
        ["ANALYSIS_FAILED"],
        "koord",
        True,
    )
    assert fake.store.events(letter_id)[0]["owner"] == "koord"


def test_unreadable_photo():
    fake = Fake(text="  ~ ; \n ..")
    letter_id = fake.upload()
    assert process(fake.services, letter_id) == "unreadable"
    assert fake.calls == {"ocr": 1, "inspect": 0, "analyze": 0}
    assert "raw_text" not in fake.store.get_letter(letter_id)


def test_missing_letter():
    assert process(Fake().services, "nope") == "missing"
