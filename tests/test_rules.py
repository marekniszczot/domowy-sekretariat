import pytest

from sekretariat.household import Member, Role
from sekretariat.rules import InvalidRule, compose, next_id

EWA = Member("ewa", Role.DOMOWNIK, ("Ewa", "Ewy", "Ewie"), ("Nowak",), ("e@example.com",))
JAN = Member("jan", Role.KOORDYNATOR, ("Jan", "Jana"), ("Nowak",), ("j@example.com",))
HOUSE = [EWA, JAN]


@pytest.mark.parametrize(
    "sentence, member, sender, expected",
    [
        ("Rachunki za prąd ogarnia Ewa", EWA, None, "Rachunki za prąd ogarnia OSOBA_1."),
        ("Pisma z banku", JAN, "Bank", "Pisma z banku. Zajmuje się tym OSOBA_2. Dotyczy: Bank."),
        (
            "  Podwyżki   bez akcji: nic nie robimy! ",
            None,
            None,
            "Podwyżki bez akcji: nic nie robimy!",
        ),
        ("Wszystko od Jana dla Ewy", EWA, None, "Wszystko od OSOBA_2 dla OSOBA_1."),
    ],
)
def test_rule_text_has_placeholders_only(sentence, member, sender, expected):
    assert compose(sentence, member, sender, HOUSE)[0] == expected


def test_display_keeps_the_sentence_as_written():
    text, display = compose("Wszystko od urzędu do Jana", JAN, "Urząd", HOUSE)
    assert text == "Wszystko od urzędu do OSOBA_2. Dotyczy: Urząd."
    assert display == "Wszystko od urzędu do Jana. Dotyczy: Urząd."
    assert compose("Bank", EWA, None, HOUSE)[1] == "Bank. Zajmuje się tym Ewa."


@pytest.mark.parametrize("sentence", ["", "   ", "x" * 301])
def test_invalid_sentences(sentence):
    with pytest.raises(InvalidRule):
        compose(sentence, None, None, HOUSE)


@pytest.mark.parametrize(
    "existing, counter, expected",
    [
        ([], 1, ("R1", 2)),
        (["R1", "R2"], 3, ("R3", 4)),
        (["R1"], 5, ("R5", 6)),  # R2..R4 were deleted: never reused
        (["R7", "inny"], 1, ("R8", 9)),  # seeded by hand before the counter
    ],
)
def test_next_id_is_never_reused(existing, counter, expected):
    assert next_id(existing, counter) == expected
