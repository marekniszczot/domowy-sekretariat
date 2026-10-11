from datetime import date, timedelta

import pytest

from sekretariat.config import ConfigError
from sekretariat.household import Member, Role
from sekretariat.jobs.__main__ import main
from sekretariat.jobs.reminders import Step, _others, due_step, remind
from sekretariat.mailer import MemoryMailer
from sekretariat.store import MemoryStore

DOM1 = Member("dom1", Role.DOMOWNIK, ("Jan",), (), ("jan@example.com",))
KOORD = Member("koord", Role.KOORDYNATOR, ("Piotr",), (), ("piotr@example.com", "p2@example.com"))
SENIOR = Member("senior", Role.BEZ_KONTA, ("Zofia",))
HOUSE = [DOM1, KOORD, SENIOR]
MONDAY = date(2026, 10, 12)
BASE = "https://sekretariat.example"


def letter(due: date | None, **fields) -> dict:
    return {
        "status": "verdict",
        "state": "open",
        "owner": "dom1",
        "verdict": "SELF",
        "analysis": {"sender_type": "BANK"},
        "deadline": {"date": due.isoformat(), "basis": "STATED", "confirmed": False}
        if due
        else None,
    } | fields


class House:
    def __init__(self):
        self.store = MemoryStore()
        self.mailer = MemoryMailer()

    def add(self, due, **fields) -> str:
        return self.store.create_letter(letter(due, **fields))

    def run(self, day, letter_ids=None):
        return remind(self.store, HOUSE, self.mailer, BASE, day, letter_ids)

    def take_sent(self):
        sent, self.mailer.sent = self.mailer.sent, []
        return sent


@pytest.fixture
def house():
    return House()


# Which step is due


@pytest.mark.parametrize(
    "days, expected",
    [
        (10, None),
        (4, None),
        (3, Step.T3),
        (2, Step.T3),
        (1, Step.T1),
        (0, Step.T0),
        (-1, Step.OVERDUE),
        (-30, Step.OVERDUE),
    ],
)
def test_step_by_days_left(days, expected):
    assert due_step({"id": "x", **letter(MONDAY + timedelta(days))}, MONDAY) == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"state": "closed"},
        {"deadline": None},
        {"owner": None},
        {"status": "received", "state": None},
    ],
)
def test_no_reminder_without_open_letter_deadline_and_owner(fields):
    assert due_step(letter(MONDAY) | fields, MONDAY) is None


def test_none_verdict_and_unconfirmed_deadline_are_reminded():
    assert due_step(letter(MONDAY, verdict="NONE"), MONDAY) == Step.T0


# Sequences over days (D3 table)


def days_with_email(house, first, last):
    days = []
    day = first
    while day <= last:
        house.run(day)
        if house.take_sent():
            days.append((day - MONDAY).days)
        day += timedelta(1)
    return days


def test_uploaded_five_days_ahead_gets_t3_t1_t0_then_daily_overdue(house):
    house.add(MONDAY + timedelta(5))
    assert days_with_email(house, MONDAY, MONDAY + timedelta(8)) == [2, 4, 5, 6, 7, 8]


def test_uploaded_two_days_ahead_gets_one_email_now_then_t1_t0(house):
    house.add(MONDAY + timedelta(2))
    assert days_with_email(house, MONDAY, MONDAY + timedelta(2)) == [0, 1, 2]


def test_uploaded_one_day_ahead_skips_t3(house):
    letter_id = house.add(MONDAY + timedelta(1))
    house.run(MONDAY)
    assert len(house.take_sent()) == 1
    assert house.store.get_letter(letter_id)["reminded"]["steps"] == ["T-3", "T-1"]


def test_uploaded_after_the_deadline_gets_overdue(house):
    house.add(MONDAY - timedelta(3))
    house.run(MONDAY)
    [(_, email)] = house.take_sent()
    assert email.subject == "Po terminie: Bank"
    assert "termin minął w piątek, 9 października" in email.text


def test_rerun_on_the_same_day_sends_nothing(house):
    house.add(MONDAY + timedelta(1))
    house.add(MONDAY - timedelta(1))
    house.run(MONDAY)
    assert len(house.take_sent()) == 1
    outcome = house.run(MONDAY)
    assert house.take_sent() == [] and outcome.sent == 0


def test_corrected_date_starts_over(house):
    letter_id = house.add(MONDAY + timedelta(1))
    house.run(MONDAY)
    house.take_sent()
    deadline = house.store.get_letter(letter_id)["deadline"]
    house.store.update_letter(
        letter_id, {"deadline": deadline | {"date": (MONDAY + timedelta(3)).isoformat()}}
    )
    house.run(MONDAY)
    [(_, email)] = house.take_sent()
    assert email.subject == "Za 3 dni termin: Bank"


def test_new_owner_gets_the_current_step(house):
    letter_id = house.add(MONDAY + timedelta(1))
    house.run(MONDAY)
    house.take_sent()
    house.store.update_letter(letter_id, {"owner": "koord"})
    house.run(MONDAY)
    [(to, _)] = house.take_sent()
    assert to == "piotr@example.com"  # the first address


def test_done_stops_and_reopen_resumes_with_the_next_step(house):
    letter_id = house.add(MONDAY + timedelta(1))
    house.run(MONDAY)
    house.take_sent()
    house.store.update_letter(letter_id, {"state": "closed"})
    house.run(MONDAY + timedelta(1))
    assert house.take_sent() == []
    house.store.update_letter(letter_id, {"state": "open"})
    house.run(MONDAY + timedelta(1))
    [(_, email)] = house.take_sent()
    assert email.subject == "Dziś termin: Bank"


# Sending


def test_failed_send_marks_nothing_and_the_next_run_retries(house):
    letter_id = house.add(MONDAY)
    house.mailer.fail = True
    outcome = house.run(MONDAY)
    assert (outcome.sent, outcome.failed) == (0, 1)
    assert "reminded" not in house.store.get_letter(letter_id)
    house.mailer.fail = False
    assert house.run(MONDAY).sent == 1
    assert len(house.take_sent()) == 1


def test_one_email_per_owner_with_the_most_urgent_letter_first(house):
    house.add(MONDAY + timedelta(3), analysis={"sender_type": "ZUS"})
    house.add(MONDAY + timedelta(1))
    house.add(MONDAY + timedelta(2), analysis={"sender_type": "URZAD"})
    house.add(MONDAY, owner="koord", analysis={"sender_type": "ENERGIA"})
    outcome = house.run(MONDAY)
    sent = dict(house.take_sent())
    assert outcome.sent == 4
    assert sent["jan@example.com"].subject == "Jutro termin: Bank i 2 inne pisma"
    text = sent["jan@example.com"].text
    assert text.index("Bank") < text.index("Urząd") < text.index("ZUS")
    assert sent["piotr@example.com"].subject == "Dziś termin: Dostawca energii"


def test_owner_without_email_is_skipped(house):
    house.add(MONDAY, owner="senior")
    outcome = house.run(MONDAY)
    assert (outcome.sent, outcome.failed) == (0, 1)
    assert house.take_sent() == []


def test_only_the_given_letters(house):
    house.add(MONDAY)
    chosen = house.add(MONDAY, analysis={"sender_type": "ZUS"})
    house.run(MONDAY, [chosen, "missing"])
    [(_, email)] = house.take_sent()
    assert email.subject == "Dziś termin: ZUS"


# Content (D7)

SECRET_FIELDS = {
    "raw_text": "SEKRET-raw Jan Testowy PESEL 44051401359",
    "masked_text": "SEKRET-masked",
    "segments": [{"text": "SEKRET-segment"}],
    "reasons": ["SEKRET-reason"],
    "addressee": "SEKRET-addressee",
    "analysis": {
        "sender_type": "BANK",
        "summary_plain_pl": "SEKRET-summary",
        "required_action": "SEKRET-action 1234,56 zł",
        "rule_trigger_quote": "SEKRET-quote",
        "deadline_quote": "SEKRET-deadline-quote",
        "consequence_quote": "SEKRET-consequence",
    },
}


def test_email_carries_metadata_only(house):
    letter_id = house.add(MONDAY + timedelta(1), private=True, **SECRET_FIELDS)
    house.run(MONDAY)
    [(_, email)] = house.take_sent()
    for part in (email.subject, email.text, email.html):
        assert "SEKRET" not in part
        assert "1234" not in part and "Jan" not in part
    assert f"{BASE}/pisma/{letter_id}" in email.text
    assert f'href="{BASE}/pisma/{letter_id}"' in email.html
    assert "Bank" in email.text and "jutro · najpóźniej do wtorku, 13 października" in email.text


def test_unconfirmed_deadline_says_so(house):
    house.add(MONDAY + timedelta(1))
    house.add(
        MONDAY + timedelta(1), owner="koord", deadline={"date": "2026-10-13", "confirmed": True}
    )
    house.run(MONDAY)
    sent = dict(house.take_sent())
    assert "Termin niezatwierdzony" in sent["jan@example.com"].text
    assert "Termin niezatwierdzony" not in sent["piotr@example.com"].text
    assert "jutro · do wtorku, 13 października" in sent["piotr@example.com"].text


@pytest.mark.parametrize(
    "count, words",
    [
        (1, "1 inne pismo"),
        (2, "2 inne pisma"),
        (4, "4 inne pisma"),
        (5, "5 innych pism"),
        (12, "12 innych pism"),
        (22, "22 inne pisma"),
    ],
)
def test_other_letters_plural(count, words):
    assert _others(count) == words


# Job entrypoint


def test_job_needs_smtp_settings():
    with pytest.raises(ConfigError, match="SMTP_HOST.*SMTP_PASSWORD"):
        main({"PROJECT_ID": "p", "BASE_URL": BASE})
