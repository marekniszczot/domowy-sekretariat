from datetime import date

import pytest

from sekretariat.household import Member, Role
from sekretariat.web import present
from sekretariat.web.present import State

TODAY = date(2026, 10, 9)  # Friday
EWA = Member("ewa", Role.DOMOWNIK, ("Ewa", "Ewy"), emails=("e@example.com",))
JAN = Member("jan", Role.KOORDYNATOR, ("Jan",), emails=("j@example.com",), display_name="Tata")
HOUSE = [EWA, JAN]


def letter(verdict="SELF", reasons=(), deadline=None, confirmed=False, status="verdict", **extra):
    fields = {
        "status": status,
        "verdict": verdict,
        "reasons": list(reasons),
        "deadline": {"date": deadline, "basis": "STATED", "confirmed": confirmed}
        if deadline
        else None,
        "state": "open",
    }
    return fields | extra


# DR-4: four states, never the codes


@pytest.mark.parametrize(
    "fields, expected",
    [
        (letter("NONE"), State.OK),
        (letter("NONE", deadline="2026-10-10"), State.OK),  # nothing to do, even when close
        (letter("SELF"), State.TODO),
        (letter("FORWARD"), State.TODO),
        (letter("SELF", deadline="2026-10-13"), State.TODO),  # 4 days
        (letter("SELF", deadline="2026-10-12"), State.URGENT),  # 3 days
        (letter("SELF", deadline="2026-10-01"), State.URGENT),  # overdue
        (letter("FORWARD", ["LOW_CONFIDENCE"]), State.UNSURE),
        (letter("FORWARD", ["QUOTE_NOT_FOUND", "UNKNOWN_RULE"]), State.UNSURE),
        (letter("FORWARD", ["LOW_CONFIDENCE"], deadline="2026-10-10"), State.URGENT),
        (letter("FORWARD", ["ESCALATION"]), State.URGENT),
        (letter("FORWARD", ["ESCALATION", "LOW_CONFIDENCE"]), State.URGENT),
        (letter("FORWARD", ["ANALYSIS_FAILED"], status="failed"), State.UNSURE),
        ({"status": "unreadable"}, State.UNSURE),
        ({"status": "received"}, None),
        ({"status": "masked"}, None),
        (letter("SELF", deadline="2026-10-01") | {"state": "closed"}, State.TODO),
    ],
)
def test_state(fields, expected):
    assert present.state(fields, TODAY) == expected


@pytest.mark.parametrize(
    "fields, expected",
    [
        (letter("FORWARD", ["QUOTE_NOT_FOUND"]), "cytat nie zgadza się z pismem"),
        (letter("FORWARD", ["LOW_CONFIDENCE", "UNKNOWN_RULE"]), "niska pewność"),
        (letter("FORWARD", ["MISSING_RULE"]), "żadna zasada nie pasuje"),
        (letter("FORWARD", ["ANALYSIS_FAILED"], status="failed"), "nie udało się przeanalizować"),
        ({"status": "unreadable"}, "zdjęcie nieczytelne"),
        (letter("SELF"), None),
    ],
)
def test_unsure_reason_in_words(fields, expected):
    assert present.unsure_reason(fields) == expected


# Dates in words


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 10, 9), "dziś"),
        (date(2026, 10, 10), "jutro"),
        (date(2026, 10, 11), "za 2 dni"),
        (date(2026, 10, 15), "za 6 dni"),
        (date(2026, 10, 8), "1 dzień po terminie"),
        (date(2026, 10, 2), "7 dni po terminie"),
    ],
)
def test_countdown(day, expected):
    assert present.countdown(day, TODAY) == expected


@pytest.mark.parametrize(
    "day, until, on",
    [
        (date(2026, 10, 15), "do czwartku, 15 października", "w czwartek, 15 października"),
        (date(2026, 10, 13), "do wtorku, 13 października", "we wtorek, 13 października"),
        (date(2026, 10, 14), "do środy, 14 października", "w środę, 14 października"),
        (date(2026, 11, 1), "do niedzieli, 1 listopada", "w niedzielę, 1 listopada"),
        (date(2027, 1, 4), "do poniedziałku, 4 stycznia 2027", "w poniedziałek, 4 stycznia 2027"),
    ],
)
def test_long_dates(day, until, on):
    assert present.until_date(day, TODAY) == until
    assert present.on_date(day, TODAY) == on


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2026, 10, 9), "przyszło dziś"),
        (date(2026, 10, 8), "przyszło wczoraj"),
        (date(2026, 9, 30), "przyszło 30 września"),
    ],
)
def test_delivered(day, expected):
    assert present.delivered(day, TODAY) == expected


@pytest.mark.parametrize(
    "fields, expected",
    [
        (
            letter("SELF", deadline="2026-10-15", confirmed=True),
            "za 6 dni · do czwartku, 15 października",
        ),
        (
            letter("SELF", deadline="2026-10-15"),
            "za 6 dni · najpóźniej do czwartku, 15 października",
        ),
        (letter("SELF", deadline="2026-10-07"), "termin minął w środę, 7 października"),
        (letter("SELF"), "bez terminu"),
        (letter("NONE"), "bez terminu"),
        (letter("FORWARD", ["QUOTE_NOT_FOUND"]), "cytat nie zgadza się z pismem"),
    ],
)
def test_stamp_when_line(fields, expected):
    assert present.when_line(fields, TODAY) == expected


@pytest.mark.parametrize(
    "fields, expected",
    [
        (letter("SELF", analysis={"required_action": "Opłać rachunek."}), "Opłać rachunek"),
        (letter("NONE", analysis={"required_action": ""}), "Zachowaj do wiadomości"),
        (letter("FORWARD", ["LOW_CONFIDENCE"], analysis={"required_action": "x"}), "Przekaż dalej"),
        (letter("FORWARD", ["ANALYSIS_FAILED"], status="failed"), "Przekaż dalej"),
        (
            letter("FORWARD", ["ESCALATION"], analysis={"required_action": "Odpowiedz."}),
            "Odpowiedz",
        ),
        (letter("SELF", analysis={"required_action": ""}), "Zajmij się tym pismem"),
    ],
)
def test_verb(fields, expected):
    assert present.verb(fields, TODAY) == expected


# Placeholders become names only for display


def test_names_replace_placeholders():
    text = "OSOBA_1 dostaje pismo, OSOBA_2 płaci, INNA_3 i INNA świadkami, OSOBA_DOMU, OSOBA_12."
    assert present.with_names(text, HOUSE) == (
        "Ewa dostaje pismo, Tata płaci, inna osoba i inna osoba świadkami, Wasz dom, OSOBA_12."
    )


def test_inflected_placeholders_become_names_too():
    text = "Podatek dla OSOBY_1 i OSOBY_2. Przekazać pismo OSOBIE_2, z INNĄ_1, OSOBA_DOMU."
    assert present.with_names(text, HOUSE) == (
        "Podatek dla Ewa i Tata. Przekazać pismo Tata, z inna osoba, Wasz dom."
    )


def test_quote_context_marks_the_span():
    raw = "Szanowni Państwo, prosimy o zapłatę do dnia 15.10.2026 r. pod rygorem odsetek."
    start = raw.index("do dnia")
    before, marked, after = present.quote_context(raw, (start, start + 21), radius=12)
    assert (before, marked, after) == ("…o zapłatę ", "do dnia 15.10.2026 r.", " pod rygorem…")


def test_quote_context_at_text_edges_has_no_ellipsis():
    assert present.quote_context("Zapłać 10 zł.", (0, 6), radius=40) == ("", "Zapłać", " 10 zł.")


def test_sender_labels_and_unknown_type():
    assert present.sender_label("TELEKOMUNIKACJA") == "Operator telekomunikacyjny"
    assert present.sender_label("PRACODAWCA") == "Pracodawca"
    assert present.sender_label(None) == "Nowe pismo"
    assert present.sender_label("COS_NOWEGO") == "Inny nadawca"


def test_every_sender_type_has_a_label():
    from sekretariat.llm import SenderType

    assert set(present.SENDERS) == {t.value for t in SenderType}


@pytest.mark.parametrize(
    "confidence, expected", [(0.95, "Pewne"), (0.9, "Pewne"), (0.85, "Sprawdź"), (None, "Sprawdź")]
)
def test_confidence_in_words(confidence, expected):
    assert present.confidence_word({"analysis": {"confidence": confidence}}) == expected


def test_guard_doubt_overrides_the_model_confidence():
    letter = {"analysis": {"confidence": 1}, "reasons": ["QUOTE_NOT_FOUND", "ESCALATION"]}
    assert present.confidence_word(letter) == "Sprawdź"
    assert present.confidence_word(letter | {"reasons": ["ESCALATION"]}) == "Pewne"


# Lists (DR-3)


def row(fields, created=0, **extra):
    from datetime import UTC, datetime

    return (
        {"id": f"L{created}", "created_at": datetime.fromtimestamp(created, UTC)} | fields | extra
    )


def test_groups_in_order_and_empty_groups_hidden():
    letters = [
        row(letter("NONE"), 1),
        row(letter("SELF", deadline="2026-10-20", confirmed=True), 2),
        row(letter("SELF", deadline="2026-10-12", confirmed=True), 3),
        row(letter("SELF", deadline="2026-10-01", confirmed=True), 4),
        row(letter("SELF", deadline="2026-10-14"), 5),
        row(letter("FORWARD", ["LOW_CONFIDENCE"]), 6),
        row({"status": "received"}, 7),
        row(letter("SELF") | {"state": "closed"}, 8),
        row(letter("SELF", deadline="2026-10-11", confirmed=True), 9),
    ]
    groups = present.group(letters, TODAY)
    assert [(g.title, [r["id"] for r in g.letters]) for g in groups] == [
        ("W trakcie", ["L7"]),
        ("Po terminie", ["L4"]),
        ("Do sprawdzenia", ["L5", "L6"]),
        ("Ten tydzień", ["L9", "L3"]),
        ("Później i bez terminu", ["L2", "L1"]),
        ("Zrobione", ["L8"]),
    ]


def test_metadata_only_letters_are_grouped_by_deadline():
    private = {"id": "P", "status": "verdict", "state": "open", "private": True,
               "deadline": {"date": "2026-10-12", "confirmed": True}}  # fmt: skip
    assert [g.title for g in present.group([private], TODAY)] == ["Ten tydzień"]


def test_stamp_label_reads_as_sentences():
    fields = letter("SELF", deadline="2026-10-15", confirmed=True)
    assert present.stamp_label(fields, TODAY, "Wypowiedz umowę") == (
        "Do zrobienia. Wypowiedz umowę. Za 6 dni, do czwartku, 15 października."
    )
