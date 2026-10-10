from datetime import date

import pytest

from sekretariat.deadlines import Basis, Deadline, add, compute_deadline
from sekretariat.llm import DeadlineUnit, LetterAnalysis

FRIDAY = date(2026, 10, 9)


def analysis(**overrides) -> LetterAnalysis:
    fields = {
        "sender_type": "URZAD",
        "addressee": "OSOBA_1",
        "summary_plain_pl": "Trzeba odpowiedzieć.",
        "required_action": "Odpowiedzieć na pismo.",
        "verdict": "SELF",
        "rule_id": "R1",
        "rule_trigger_quote": "prosimy o odpowiedź",
        "deadline_type": "RELATIVE",
        "deadline_date": None,
        "deadline_relative_amount": 14,
        "deadline_relative_unit": "DAYS",
        "deadline_quote": "w terminie 14 dni od dnia doręczenia",
        "consequence_quote": None,
        "letter_date": None,
        "letter_date_quote": None,
        "confidence": 0.9,
    }
    return LetterAnalysis(**(fields | overrides))


def test_no_deadline():
    assert compute_deadline(analysis(deadline_type="NONE", deadline_quote=None), FRIDAY) is None


def test_absolute_deadline_is_stated_as_is():
    result = compute_deadline(
        analysis(deadline_type="ABSOLUTE", deadline_date="2026-11-30", deadline_quote="do 30.11"),
        FRIDAY,
    )
    assert result == Deadline(date(2026, 11, 30), Basis.STATED)
    assert not result.computed


# D10 table: delivery day not counted, calendar days, no shift to a working day.


@pytest.mark.parametrize(
    "delivered, amount, expected",
    [
        (FRIDAY, 14, date(2026, 10, 23)),  # Friday delivery
        (date(2026, 10, 2), 14, date(2026, 10, 16)),
        (FRIDAY, 1, date(2026, 10, 10)),  # ends on a Saturday: no shift to Monday
        (FRIDAY, 2, date(2026, 10, 11)),  # ends on a Sunday: no shift
        (date(2026, 10, 18), 14, date(2026, 11, 1)),  # ends on All Saints' Day: no shift
        (date(2026, 10, 25), 7, date(2026, 11, 1)),  # month boundary
        (date(2026, 12, 20), 14, date(2027, 1, 3)),  # year boundary
        (date(2028, 2, 22), 7, date(2028, 2, 29)),  # leap year
    ],
)
def test_relative_days_from_delivery(delivered, amount, expected):
    result = compute_deadline(analysis(deadline_relative_amount=amount), delivered)
    assert result == Deadline(expected, Basis.DELIVERY)
    assert result.computed


def test_working_days_are_counted_as_calendar_days():
    result = compute_deadline(
        analysis(
            deadline_relative_amount=7,
            deadline_quote="w ciągu 7 dni roboczych od otrzymania pisma",
        ),
        FRIDAY,
    )
    assert result == Deadline(date(2026, 10, 16), Basis.DELIVERY)


@pytest.mark.parametrize(
    "quote",
    [
        "w terminie 14 dni od dnia doręczenia",
        "14 dni od daty otrzymania niniejszego pisma",
        "w ciągu 14 dni od odbioru",
        "14 dni od dnia odebrania przesyłki",
        "W TERMINIE 14 DNI OD DORĘCZENIA",
    ],
)
def test_quote_naming_delivery_anchors_on_delivery(quote):
    assert compute_deadline(analysis(deadline_quote=quote), FRIDAY).basis == Basis.DELIVERY


# D8: the model's anchor is not trusted.


def test_unknown_anchor_uses_letter_date():
    result = compute_deadline(
        analysis(
            deadline_quote="w terminie 14 dni",
            letter_date="2026-10-02",
            letter_date_quote="Warszawa, 2 października 2026 r.",
        ),
        FRIDAY,
    )
    assert result == Deadline(date(2026, 10, 16), Basis.LETTER_DATE)


def test_anchor_from_issue_date_uses_letter_date():
    result = compute_deadline(
        analysis(
            deadline_quote="14 dni od daty wystawienia",
            letter_date="2026-10-02",
            letter_date_quote="2026-10-02",
        ),
        FRIDAY,
    )
    assert result == Deadline(date(2026, 10, 16), Basis.LETTER_DATE)


def test_letter_date_after_delivery_falls_back_to_delivery():
    result = compute_deadline(
        analysis(
            deadline_quote="w terminie 14 dni",
            letter_date="2026-10-20",
            letter_date_quote="20.10.2026",
        ),
        FRIDAY,
    )
    assert result == Deadline(date(2026, 10, 23), Basis.LETTER_DATE)


def test_unknown_anchor_without_letter_date_assumes_delivery():
    result = compute_deadline(
        analysis(deadline_relative_amount=7, deadline_quote="w terminie 7 dni"), FRIDAY
    )
    assert result == Deadline(date(2026, 10, 16), Basis.ASSUMED_DELIVERY)


# Units


@pytest.mark.parametrize(
    "start, amount, unit, expected",
    [
        (FRIDAY, 2, DeadlineUnit.WEEKS, date(2026, 10, 23)),
        (date(2026, 1, 31), 1, DeadlineUnit.MONTHS, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, DeadlineUnit.MONTHS, date(2028, 2, 29)),
        (date(2026, 3, 31), 1, DeadlineUnit.MONTHS, date(2026, 4, 30)),
        (date(2026, 11, 15), 3, DeadlineUnit.MONTHS, date(2027, 2, 15)),
        (date(2026, 12, 31), 12, DeadlineUnit.MONTHS, date(2027, 12, 31)),
    ],
)
def test_add_units(start, amount, unit, expected):
    assert add(start, amount, unit) == expected


def test_relative_months_from_delivery():
    result = compute_deadline(
        analysis(
            deadline_relative_amount=1,
            deadline_relative_unit="MONTHS",
            deadline_quote="w terminie miesiąca od dnia doręczenia",
        ),
        date(2026, 1, 31),
    )
    assert result == Deadline(date(2026, 2, 28), Basis.DELIVERY)
