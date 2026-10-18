import pytest

from sekretariat.inflect import placeholder_case, unsure_case


def at(text: str) -> int:
    return text.index("OSOB")


@pytest.mark.parametrize(
    "text, case",
    [
        ("OSOBA_1 ma zaległość.", None),
        ("Bank pisze, że OSOBA_1 ma zaległość.", None),
        ("Faktura dla OSOBA_1.", "dopelniacz"),
        ("Pismo do „OSOBA_1”.", "dopelniacz"),
        ("ZUS wzywa OSOBA_1 do zapłaty.", "biernik"),
        ("Ulga przysługuje OSOBA_1.", "celownik"),
        ("Umowa z OSOBA_1.", "narzednik"),
        ("Rozmowa o OSOBA_1.", "miejscownik"),
        ("Pismo otrzymał OSOBA_1.", None),
        ("Koniec. OSOBA_1 płaci.", None),
        ("Dla OSOBY_1.", "dopelniacz"),
        ("Przekazać OSOBIE_1.", "celownik"),
        ("Mowa o OSOBIE_1.", "miejscownik"),
    ],
)
def test_placeholder_case(text, case):
    ending = text[at(text) + 4 : text.index("_", at(text))]
    assert placeholder_case(text, at(text), ending) == case


@pytest.mark.parametrize(
    "text, unsure",
    [
        ("OSOBA_1 płaci.", False),
        ("Faktura dla OSOBA_1.", False),
        ("Wyniki badań OSOBA_3 są gotowe.", True),
        ("Pismo otrzymał OSOBA_1.", True),  # nominative here, but the code cannot tell
    ],
)
def test_unsure_case(text, unsure):
    assert unsure_case(text, at(text)) == unsure
