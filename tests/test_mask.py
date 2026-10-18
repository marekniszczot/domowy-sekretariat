import os
import re
import subprocess
from types import SimpleNamespace

import pytest

from sekretariat.household import Member
from sekretariat.mask import (
    ELEVEN_DIGITS,
    ELEVEN_DIGITS_PATTERN,
    PERSON,
    POLISH_STREET,
    POSTAL_CODE,
    POSTAL_CODE_PATTERN,
    STREET_PATTERN,
    Finding,
    inspect,
    mask,
    pesel_valid,
)

# Synthetic data only. 44051401359 is the textbook example PESEL.
JAN = Member(
    "jan",
    first_name_forms=("Jan", "Jana", "Janowi", "Janem", "Janie"),
    surname_forms=("Nowak", "Nowaka", "Nowakowi"),
)
# "Nowak" is the family name shared with JAN; "Nowaka" and "Nowakowi" are only his.
EWA = Member("ewa", first_name_forms=("Ewa", "Ewy", "Ewie", "Ewę", "Ewą"), surname_forms=("Nowak",))
ZOFIA = Member("zofia", first_name_forms=("Zofia",), surname_forms=("Wzorcowa", "Wzorcowej"))


def find(text: str, quote: str, info_type: str, occurrence: int = 0) -> Finding:
    starts = [m.start() for m in re.finditer(re.escape(quote), text)]
    start = starts[occurrence]
    return Finding(start, start + len(quote), info_type)


# PESEL (D4, D6)


def test_pesel_checksum():
    assert pesel_valid("44051401359")
    assert not pesel_valid("44051401358")
    assert not pesel_valid("4405140135")
    assert not pesel_valid("4405140135a")


@pytest.mark.parametrize(
    "text",
    ["44051401359", "440 514 013 59", "4405-1401-359", "Nr 12345678901."],
)
def test_eleven_digit_pattern_matches(text):
    assert re.search(ELEVEN_DIGITS_PATTERN, text)


@pytest.mark.parametrize(
    "text",
    ["4405140135", "440514013590", "PL61 1090 1014 0000 0712 1981 2874", "ref A44051401359"],
)
def test_eleven_digit_pattern_ignores(text):
    assert not re.search(ELEVEN_DIGITS_PATTERN, text)


def test_eleven_digits_labelled_by_checksum():
    text = "PESEL 440 514 013 59, sygnatura 12345678901."
    findings = [
        find(text, "440 514 013 59", ELEVEN_DIGITS),
        find(text, "12345678901", ELEVEN_DIGITS),
    ]
    assert mask(text, findings, []).masked_text == "PESEL [PESEL], sygnatura [NUMER]."


def test_builtin_and_custom_pesel_merge_into_one_label():
    text = "PESEL 44051401359."
    findings = [
        find(text, "44051401359", "POLAND_PESEL_NUMBER"),
        find(text, "44051401359", ELEVEN_DIGITS),
    ]
    result = mask(text, findings, [])
    assert result.masked_text == "PESEL [PESEL]."
    assert len(result.segments) == 1


def test_phone_wins_over_eleven_digit_number():
    text = "tel. +48 600 700 800"
    findings = [
        find(text, "+48 600 700 800", "PHONE_NUMBER"),
        find(text, "48 600 700 800", ELEVEN_DIGITS),
    ]
    assert mask(text, findings, []).masked_text == "tel. [TELEFON]"


def test_dashed_pesel_seen_as_phone_is_still_pesel():
    text = "PESEL 4405-1401-359"
    findings = [
        find(text, "4405-1401-359", "PHONE_NUMBER"),
        find(text, "4405-1401-359", ELEVEN_DIGITS),
    ]
    assert mask(text, findings, []).masked_text == "PESEL [PESEL]"


# Identifiers (D7)


def test_identifier_labels():
    text = "Dowód ABA300000, paszport ZS0000177, IBAN PL61109010140000071219812874, ul. Długa 5"
    findings = [
        find(text, "ABA300000", "POLAND_NATIONAL_ID_NUMBER"),
        find(text, "ZS0000177", "POLAND_PASSPORT"),
        find(text, "PL61109010140000071219812874", "IBAN_CODE"),
        find(text, "Długa 5", "STREET_ADDRESS"),
    ]
    assert mask(text, findings, []).masked_text == (
        "Dowód [DOWOD], paszport [PASZPORT], IBAN [IBAN], ul. [ADRES]"
    )


def test_email_wins_over_person_parts():
    text = "e-mail jan.nowak@example.com."
    findings = [
        find(text, "jan", PERSON),
        find(text, "nowak", PERSON),
        find(text, "jan.nowak@example.com", "EMAIL_ADDRESS"),
    ]
    assert mask(text, findings, []).masked_text == "e-mail [EMAIL]."


# Household members (D5, D15)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Szanowny Panie Janie,", "Szanowny Panie OSOBA_1,"),
        ("przekazujemy Janowi pismo", "przekazujemy OSOBA_1 pismo"),
        ("dla Jana Nowaka", "dla OSOBA_1"),
        ("dla Jana\nNowaka", "dla OSOBA_1"),
        ("PANI EWY", "PANI OSOBA_2"),
        ("z Ewą i Janem", "z OSOBA_2 i OSOBA_1"),
    ],
)
def test_member_forms_without_dlp(text, expected):
    assert mask(text, [], [JAN, EWA]).masked_text == expected


def test_member_form_is_whole_word_only():
    text = "Janowiec, Ewangelia, Nowakowski"
    assert mask(text, [], [JAN, EWA]).masked_text == text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nowak Jan", "OSOBA_1"),
        ("Nowak, Jan", "OSOBA_1"),
        ("NOWAKA JANA", "OSOBA_1"),
        ("Nowak\nJan", "OSOBA_1"),
        ("Ewa Nowak i Jan Nowak", "OSOBA_2 i OSOBA_1"),
        ("Nowak, Ewa", "OSOBA_2"),
        ("Pan Nowakowi", "Pan OSOBA_1"),  # surname form only Jan has
        ("Pani Wzorcowej", "Pani OSOBA_3"),  # surname of one member
        ("Państwo Nowak", "Państwo OSOBA_DOMU"),  # family name: not known who
    ],
)
def test_first_names_and_surnames_in_any_order(text, expected):
    assert mask(text, [], [JAN, EWA, ZOFIA]).masked_text == expected


def test_lowercase_common_word_is_not_a_name():
    # A name form may also be a word: "Róża" (a name) vs "róża" (a rose).
    member = Member("m", first_name_forms=("Róża", "Róży"), surname_forms=("Wilk",))
    text = "Nie płać róży nie dzwoń; wilk syty. Pani Róży Wilk, RÓŻY WILK."
    assert mask(text, [], [member]).masked_text == (
        "Nie płać róży nie dzwoń; wilk syty. Pani OSOBA_1, OSOBA_1."
    )


def test_named_member_wins_over_family_name_in_one_group():
    text = "Jan oraz Nowak"
    findings = [find(text, "Jan oraz Nowak", PERSON)]
    assert mask(text, findings, [JAN, EWA]).masked_text == "OSOBA_1"


def test_family_name_alone_in_dlp_span():
    text = "Szanowni Państwo Nowak"
    findings = [find(text, "Państwo Nowak", PERSON)]
    assert mask(text, findings, [JAN, EWA]).masked_text == "Szanowni OSOBA_DOMU"


def test_dlp_person_containing_member_becomes_member():
    text = "Szanowny Pan Jan Kowalski"
    findings = [find(text, "Pan Jan Kowalski", PERSON)]
    assert mask(text, findings, [JAN]).masked_text == "Szanowny OSOBA_1"


def test_two_members_in_one_person_span():
    text = "Państwo Ewa i Jan Kowalscy"
    findings = [find(text, "Ewa i Jan Kowalscy", PERSON)]
    assert mask(text, findings, [JAN, EWA]).masked_text == "Państwo OSOBA_2, OSOBA_1"


# Addresses: DLP STREET_ADDRESS misses "ul. Lipowa 7 m. 3" and addresses inside a sentence


@pytest.mark.parametrize(
    "text, address",
    [
        ("Pan Jan\nul. Lipowa 7 m. 3, 00-001 Warszawa", "Lipowa 7 m. 3"),
        ("ul. Lipowa 7/3", "Lipowa 7/3"),
        ("(garaż, ul. Lipowa 7) wynosi", "Lipowa 7"),
        ("przy ul. Handlowej 5 już w sobotę", "Handlowej 5"),
        ("Ul. Książkowa 3", "Książkowa 3"),
        ("al. Jana Pawła II 15a lok. 2", "Jana Pawła II 15a lok. 2"),
        ("ul. 3 Maja 12, Gdynia", "3 Maja 12"),
        ("os. Słoneczne 4 m 10", "Słoneczne 4 m 10"),
        ("ul. Zdrowa 1. Badania należy wykonać", "Zdrowa 1"),
    ],
)
def test_street_pattern_reports_the_street_without_its_prefix(text, address):
    # DLP reports only group 1 (group_indexes); "ul." stays, as with STREET_ADDRESS.
    assert re.search(STREET_PATTERN, text).group(1) == address


@pytest.mark.parametrize("text", ["ul. Lipowa", "Lipowa 7", "pl 15 zł", "Liczba os. 2"])
def test_street_pattern_ignores(text):
    assert not re.search(STREET_PATTERN, text)


@pytest.mark.parametrize(
    "text, code",
    [
        ("ul. Lipowa 7, 00-001 Warszawa", "00-001 Warszawa"),
        ("81-001 Przykładowo\nDECYZJA", "81-001 Przykładowo"),
        ("00-950 Warszawa\nWarszawa", "00-950 Warszawa"),
        ("kod 43-300 Bielsko-Biała", "43-300 Bielsko-Biała"),
        ("kod 00-001", "00-001"),
    ],
)
def test_postal_code_pattern_matches(text, code):
    assert re.search(POSTAL_CODE_PATTERN, text).group(0) == code


@pytest.mark.parametrize("text", ["2026-10-18", "tel. 600-700-800", "100-001"])
def test_postal_code_pattern_ignores(text):
    assert not re.search(POSTAL_CODE_PATTERN, text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ul. Lipowa 7 m. 3, 00-001 Warszawa\nDotyczy", "ul. [ADRES]\nDotyczy"),
        ("ul. Lipowa 7 m. 3\n00-001 Warszawa", "ul. [ADRES]"),
        ("ul. Lipowa 7 m. 3 oraz 00-001 Warszawa", "ul. [ADRES] oraz [ADRES]"),
    ],
)
def test_custom_address_findings_one_address_one_placeholder(text, expected):
    findings = [
        find(text, "Lipowa 7 m. 3", POLISH_STREET),
        find(text, "00-001 Warszawa", POSTAL_CODE),
    ]
    result = mask(text, findings, [])
    assert result.masked_text == expected
    assert result.to_raw(0, len(result.masked_text)) == (0, len(text))


def test_address_next_to_another_label_is_not_joined():
    text = "ul. Lipowa 7, tel. 600 700 800"
    findings = [find(text, "Lipowa 7", POLISH_STREET), find(text, "600 700 800", "PHONE_NUMBER")]
    assert mask(text, findings, []).masked_text == "ul. [ADRES], tel. [TELEFON]"


def test_household_address_forms_without_dlp():
    home = Member("jan", first_name_forms=("Jan",), address_forms=("Lipowa 7", "Lipowej 7"))
    text = "Wspólnota Mieszkaniowa Lipowa 7, LIPOWA 7, przy Lipowej 7; Lipowa 70, Lipowej 9"
    assert mask(text, [], [home]).masked_text == (
        "Wspólnota Mieszkaniowa [ADRES], przy [ADRES]; Lipowa 70, Lipowej 9"
    )


def test_household_address_wins_over_member_name_inside_it():
    home = Member("jan", first_name_forms=("Jana",), address_forms=("Jana Pawła II 5",))
    assert mask("ul. Jana Pawła II 5", [], [home]).masked_text == "ul. [ADRES]"


def test_member_name_inside_address_stays_address():
    text = "ul. Jana Pawła II 5"
    findings = [find(text, "Jana Pawła II 5", "STREET_ADDRESS")]
    assert mask(text, findings, [JAN]).masked_text == "ul. [ADRES]"


@pytest.mark.parametrize("count", [1, 2, 4])
def test_placeholders_follow_household_order(count):
    names = ["Jan", "Ewa", "Zofia", "Piotr"][:count]
    members = [Member(name.lower(), first_name_forms=(name,)) for name in names]
    text = " ".join(reversed(names))
    expected = " ".join(f"OSOBA_{i}" for i in range(count, 0, -1))
    assert mask(text, [], members).masked_text == expected


def test_first_name_form_shared_by_two_members_is_rejected():
    with pytest.raises(ValueError, match="more than one member"):
        mask(
            "", [], [Member("a", first_name_forms=("Ola",)), Member("b", first_name_forms=("ola",))]
        )


def test_form_used_as_first_name_and_surname_is_rejected():
    with pytest.raises(ValueError, match="both a first name and a surname"):
        mask(
            "",
            [],
            [Member("a", first_name_forms=("Paweł",)), Member("b", surname_forms=("Paweł",))],
        )


def test_other_people_numbered_consistently_by_spelling():
    text = "Halina Kowalska, Piotr Wiśniewski, halina  kowalska"
    findings = [
        find(text, "Halina Kowalska", PERSON),
        find(text, "Piotr Wiśniewski", PERSON),
        find(text, "halina  kowalska", PERSON),
    ]
    assert mask(text, findings, []).masked_text == "INNA_1, INNA_2, INNA_1"


def test_member_who_is_addressee_and_other_person():
    text = "Adresat: Jan Nowak. Wierzyciel: Adam Zieliński."
    findings = [find(text, "Jan Nowak", PERSON), find(text, "Adam Zieliński", PERSON)]
    assert mask(text, findings, [JAN]).masked_text == "Adresat: OSOBA_1. Wierzyciel: INNA_1."


# Offset map


DOCSTRING_EXAMPLE = "Pan Jan Nowak, PESEL 44051401359, tel. +48 600 700 800, kwota 245 zł"


def docstring_example():
    text = DOCSTRING_EXAMPLE
    findings = [
        find(text, "Pan Jan Nowak", PERSON),
        find(text, "44051401359", "POLAND_PESEL_NUMBER"),
        find(text, "44051401359", ELEVEN_DIGITS),
        find(text, "+48 600 700 800", "PHONE_NUMBER"),
        find(text, "48 600 700 800", ELEVEN_DIGITS),
    ]
    return mask(text, findings, [JAN])


def test_docstring_example():
    result = docstring_example()
    assert result.masked_text == "OSOBA_1, PESEL [PESEL], tel. [TELEFON], kwota 245 zł"
    assert [(s.raw_start, s.raw_end, s.masked_start, s.masked_end) for s in result.segments] == [
        (0, 13, 0, 7),
        (21, 32, 15, 22),
        (39, 54, 29, 38),
    ]


def test_unmasked_text_maps_exactly_both_ways():
    result = docstring_example()
    masked = result.masked_text
    for quote in ["kwota 245 zł", ", PESEL ", "tel. "]:
        start = masked.index(quote)
        raw_start, raw_end = result.to_raw(start, start + len(quote))
        assert DOCSTRING_EXAMPLE[raw_start:raw_end] == quote
        assert result.to_masked(raw_start, raw_end) == (start, start + len(quote))


def test_span_touching_a_segment_widens_to_whole_segment():
    result = docstring_example()
    masked = result.masked_text
    start = masked.index("PESEL [PES")
    raw_start, raw_end = result.to_raw(start, start + len("PESEL [PES"))
    assert DOCSTRING_EXAMPLE[raw_start:raw_end] == "PESEL 44051401359"


def test_every_masked_position_maps_inside_raw_text():
    result = docstring_example()
    n = len(result.masked_text)
    for start in range(n + 1):
        for end in range(start, n + 1):
            raw_start, raw_end = result.to_raw(start, end)
            assert 0 <= raw_start <= raw_end <= len(DOCSTRING_EXAMPLE)


def test_no_findings_is_identity():
    result = mask("Wezwanie do zapłaty 245 zł", [], [])
    assert result.masked_text == "Wezwanie do zapłaty 245 zł"
    assert result.segments == ()
    assert result.to_raw(3, 10) == (3, 10)


def test_masking_is_idempotent():
    once = docstring_example().masked_text
    assert mask(once, [], [JAN, EWA]).masked_text == once


# DLP adapter


class FakeDlp:
    def __init__(self, findings, truncated=False):
        self.request = None
        self._response = SimpleNamespace(
            result=SimpleNamespace(findings=findings, findings_truncated=truncated)
        )

    def inspect_content(self, request):
        self.request = request
        return self._response


def dlp_finding(info_type, start, end):
    return SimpleNamespace(
        info_type=SimpleNamespace(name=info_type),
        location=SimpleNamespace(codepoint_range=SimpleNamespace(start=start, end=end)),
    )


def test_inspect_builds_regional_request_and_maps_codepoints():
    client = FakeDlp([dlp_finding("POLAND_PESEL_NUMBER", 6, 17)])
    findings = inspect(client, "proj", "europe-central2", "PESEL 44051401359")

    assert findings == [Finding(6, 17, "POLAND_PESEL_NUMBER")]
    request = client.request
    assert request["parent"] == "projects/proj/locations/europe-central2"
    requested = {t["name"] for t in request["inspect_config"]["info_types"]}
    assert {"POLAND_PESEL_NUMBER", "PERSON_NAME", "EMAIL_ADDRESS"} <= requested
    custom = {t["info_type"]["name"] for t in request["inspect_config"]["custom_info_types"]}
    assert custom == {ELEVEN_DIGITS, POLISH_STREET, POSTAL_CODE}
    [street] = [t for t in request["inspect_config"]["custom_info_types"]
                if t["info_type"]["name"] == POLISH_STREET]  # fmt: skip
    assert street["regex"]["group_indexes"] == [1]
    assert not custom & requested  # built-in names only, DLP rejects unknown ones


def test_inspect_refuses_truncated_findings():
    with pytest.raises(RuntimeError, match="truncated"):
        inspect(FakeDlp([], truncated=True), "proj", "europe-central2", "x")


@pytest.mark.integration
def test_inspect_against_real_dlp():
    import google.oauth2.credentials
    from google.cloud import dlp_v2

    token = subprocess.run(
        [
            "gcloud",
            "auth",
            "print-access-token",
            f"--configuration={os.environ['GCLOUD_CONFIGURATION']}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    project = os.environ["GCP_PROJECT"]
    client = dlp_v2.DlpServiceClient(
        credentials=google.oauth2.credentials.Credentials(token, quota_project_id=project)
    )
    text = (
        "Pan Jan Nowak, numer 440 514 013 59, sygnatura 12345678901, "
        "tel. +48 600 700 800, e-mail jan.nowak@example.com. Kwota 245,00 zł.\n"
        "Adres: ul. Lipowa 7 m. 3, 81-001 Przykładowo (garaż przy ul. Lipowej 7)."
    )

    result = mask(text, inspect(client, project, "europe-central2", text), [JAN])

    for secret in ["Nowak", "440 514 013 59", "12345678901", "600 700 800", "example.com",
                   "Lipowa", "Lipowej", "81-001", "Przykładowo"]:  # fmt: skip
        assert secret not in result.masked_text
    assert "245,00 zł" in result.masked_text
    assert "[PESEL]" in result.masked_text
