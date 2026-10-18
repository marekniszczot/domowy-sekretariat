"""Which grammatical case a member placeholder stands in (DT13b).

The card replaces OSOBA_n with the member's name, and household.yaml may give the
name in each case (name_cases). The model writes placeholders uninflected, so the
case comes from the word before them, the way Polish prepositions and verbs govern it:

    "dla OSOBA_1", do, od, u, bez, według, wobec, dotyczy ──▶ dopelniacz (dla Ewy)
    "informuje OSOBA_1", wzywa, prosi, zawiadamia, przez ───▶ biernik (informuje Ewę)
    "przysługuje OSOBA_1", przypomina, przekazać, dzięki ───▶ celownik (Ewie)
    "z OSOBA_1", ze, przed, między ─────────────────────────▶ narzednik (z Ewą)
    "o OSOBA_1", w, we, przy, po ───────────────────────────▶ miejscownik (o Ewie)
    sentence start, a conjunction or any other word ────────▶ nominative

Any other word keeps the nominative, so "Pismo otrzymała OSOBA_1" stays right; the
eval reports placeholders after such words, because some of them need another case
("wyniki badań OSOBA_3"). An inflected placeholder ("OSOBY_1") carries its case in
the ending; "OSOBIE" is dative or, after a locative preposition, locative.
"""

import re

_GOVERNS = {
    "dopelniacz": "dla do od u bez według wobec dotyczy dotyczące dotyczący imieniu oprócz zamiast",
    "biernik": "informuje informują wzywa wzywają prosi proszą zawiadamia powiadamia zaprasza "
    "upomina obciąża przez",
    "celownik": "przysługuje przypomina przypominamy przekazać przekaż przekazuje dziękuje "
    "dziękujemy wysłać przyznaje przyznano dzięki",
    "narzednik": "z ze przed między",
    "miejscownik": "o w we przy po",
}
CASE_AFTER = {word: case for case, words in _GOVERNS.items() for word in words.split()}
SUBJECT_AFTER = {"i", "oraz", "a", "ale", "że", "bo", "gdy", "lub", "albo", "więc", "ponieważ"}
_ENDING = {"Y": "dopelniacz", "IE": "celownik", "Ę": "biernik", "Ą": "narzednik", "O": "wolacz"}
_WORD_BEFORE = re.compile(r"(\S+)\s+$")


def word_before(text: str, start: int) -> str | None:
    """The word right before position start, lowercased; None at a sentence start."""
    match = _WORD_BEFORE.search(text[:start].rstrip("„\"'("))
    if match is None or match.group(1).endswith((".", "!", "?", ":")):
        return None
    return match.group(1).strip("„”\"'(").lower()


def placeholder_case(text: str, start: int, ending: str = "A") -> str | None:
    """The case of the placeholder at start ("A" for OSOBA, "Y" for OSOBY...); None is
    the nominative."""
    word = word_before(text, start)
    if ending != "A":
        case = _ENDING.get(ending)
        if case == "celownik" and CASE_AFTER.get(word) == "miejscownik":
            return "miejscownik"
        return case
    return CASE_AFTER.get(word)


def unsure_case(text: str, start: int) -> bool:
    """An uninflected placeholder after a word that may need another case."""
    word = word_before(text, start)
    return word is not None and word not in SUBJECT_AFTER and word not in CASE_AFTER
