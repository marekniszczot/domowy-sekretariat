import smtplib
from datetime import UTC, date, datetime, timedelta

import pytest

from sekretariat.household import Member, Role
from sekretariat.mailer import MemoryMailer
from sekretariat.notices import FAILED, FORWARD, assigned, schedule, send
from sekretariat.store import MemoryStore

DOM1 = Member("dom1", Role.DOMOWNIK, ("Jan",), (), ("jan@example.com",))
KOORD = Member("koord", Role.KOORDYNATOR, ("Piotr",), (), ("piotr@example.com",))
SENIOR = Member("senior", Role.BEZ_KONTA, ("Zofia",))
HOUSE = [DOM1, KOORD, SENIOR]
BASE = "https://sekretariat.example"
T = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
DAY = date(2026, 10, 12)


def minutes(n: int) -> datetime:
    return T + timedelta(minutes=n)


class House:
    def __init__(self):
        self.store = MemoryStore()
        self.mailer = MemoryMailer()
        self.tasks = []

    def forward(self, at, to="dom1", by="koord", **fields) -> str:
        """A letter forwarded at `at`, then the scheduling the web app does."""
        letter_id = self.store.create_letter(
            {
                "status": "verdict",
                "state": "open",
                "owner": to,
                "taken": False,
                "analysis": {"sender_type": "BANK"},
                "deadline": {"date": "2026-10-16", "confirmed": False},
                "assigned": assigned(to, by, at, FORWARD),
            }
            | fields
        )
        schedule(self.store, lambda member, when: self.tasks.append((member, when)), to, at)
        return letter_id

    def send(self, at, member="dom1"):
        return send(self.store, HOUSE, self.mailer, BASE, member, at, DAY)

    def take_sent(self):
        sent, self.mailer.sent = self.mailer.sent, []
        return sent


@pytest.fixture
def house():
    return House()


# Timing (DR-12: soon, then at most one e-mail per 15 minutes)


def test_first_forward_goes_out_after_the_undo_window(house):
    house.forward(T)
    assert house.tasks == [("dom1", minutes(2))]


def test_forwards_while_a_task_waits_join_it(house):
    house.forward(T)
    house.forward(minutes(1), analysis={"sender_type": "ZUS"})
    assert house.tasks == [("dom1", minutes(2))]
    assert house.send(minutes(2)) == 2
    [(to, email)] = house.take_sent()
    assert to == "jan@example.com"
    assert email.subject == "Masz 2 nowe pisma do ogarnięcia"
    assert email.text.index("Bank") < email.text.index("ZUS")


def test_next_email_waits_15_minutes_after_the_last_one(house):
    house.forward(T)
    house.send(minutes(2))
    house.take_sent()
    house.forward(minutes(5), analysis={"sender_type": "ZUS"})
    assert house.tasks[-1] == ("dom1", minutes(17))
    assert house.send(minutes(17)) == 1
    [(_, email)] = house.take_sent()
    assert email.subject == "Masz nowe pismo do ogarnięcia: ZUS"


def test_quiet_member_gets_the_next_one_soon_again(house):
    house.forward(T)
    house.send(minutes(2))
    house.forward(minutes(60))
    assert house.tasks[-1] == ("dom1", minutes(62))


def test_a_task_that_never_ran_does_not_block_new_ones(house):
    house.store.set_notice("dom1", {"scheduled_at": minutes(-30)})
    house.forward(T)
    assert house.tasks == [("dom1", minutes(2))]


def test_assignment_after_the_task_started_waits_for_the_next_email(house):
    house.forward(T)
    house.forward(minutes(3))  # after the 08:02 task's cutoff
    assert house.send(minutes(2)) == 1
    assert house.store.notice("dom1")["scheduled_at"] is None
    house.forward(minutes(4))
    assert house.tasks[-1] == ("dom1", minutes(17))
    assert house.send(minutes(17)) == 2


# What counts


@pytest.mark.parametrize(
    "fields",
    [
        {"owner": "koord"},  # „Cofnij” brought it back
        {"taken": True},  # „Zajmę się tym” before the e-mail
        {"state": "closed"},
    ],
)
def test_letters_no_longer_waiting_are_not_sent(house, fields):
    letter_id = house.forward(T)
    house.store.update_letter(letter_id, fields)
    assert house.send(minutes(2)) == 0
    assert house.take_sent() == []
    assert "sent_at" not in house.store.notice("dom1")


def test_forwarding_to_oneself_is_not_sent(house):
    house.forward(T, by="dom1")
    assert house.send(minutes(2)) == 0


def test_member_without_email_gets_nothing(house):
    house.forward(T, to="senior")
    assert house.send(minutes(2), "senior") == 0
    assert house.send(minutes(2), "nobody") == 0


def test_smtp_error_raises_and_the_retry_sends(house):
    house.forward(T)
    house.mailer.fail = True
    with pytest.raises(smtplib.SMTPException):
        house.send(minutes(2))
    assert "sent_at" not in house.store.notice("dom1")
    house.mailer.fail = False
    assert house.send(minutes(3)) == 1


# Content (D7)


def test_forward_email(house):
    letter_id = house.forward(T)
    house.send(minutes(2))
    [(_, email)] = house.take_sent()
    assert email.subject == "Masz nowe pismo do ogarnięcia: Bank"
    assert "Bank: za 4 dni · najpóźniej do piątku, 16 października" in email.text
    assert "Termin niezatwierdzony" in email.text
    assert f'href="{BASE}/pisma/{letter_id}"' in email.html


def test_close_deadline_is_marked_urgent(house):
    house.forward(T, deadline={"date": "2026-10-14", "confirmed": True})
    house.send(minutes(2))
    [(_, email)] = house.take_sent()
    assert "Bank: ▲ za 2 dni · do środy, 14 października" in email.text
    assert "Termin niezatwierdzony" not in email.text


def test_forward_without_deadline(house):
    house.forward(T, deadline=None)
    house.send(minutes(2))
    [(_, email)] = house.take_sent()
    assert "Bank: bez terminu" in email.text and "▲" not in email.text


def test_failed_analysis_email(house):
    house.forward(T, to="koord", by=None, analysis=None, deadline=None,
                  assigned=assigned("koord", None, T, FAILED))  # fmt: skip
    house.send(minutes(2), "koord")
    [(to, email)] = house.take_sent()
    assert to == "piotr@example.com"
    assert email.subject == "Nie udało się przeanalizować pisma"
    assert "Nowe pismo: Nie udało się go przeanalizować" in email.text
    assert "Przejrzyj je w aplikacji" in email.text


def test_email_carries_metadata_only(house):
    house.forward(
        T,
        private=True,
        raw_text="SEKRET-raw Jan Testowy",
        masked_text="SEKRET-masked",
        analysis={
            "sender_type": "BANK",
            "summary_plain_pl": "SEKRET-summary",
            "required_action": "SEKRET-action 1234,56 zł",
            "rule_trigger_quote": "SEKRET-quote",
        },
    )
    house.send(minutes(2))
    [(_, email)] = house.take_sent()
    for part in (email.subject, email.text, email.html):
        assert "SEKRET" not in part and "1234" not in part and "Jan" not in part
