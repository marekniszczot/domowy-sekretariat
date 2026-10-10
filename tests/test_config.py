from pathlib import Path
from types import SimpleNamespace

import pytest
from google.api_core import exceptions as gcp_exceptions

from sekretariat.config import ConfigError, load_household, parse_household
from sekretariat.household import Member, Role

EXAMPLE = Path(__file__).resolve().parent.parent / "household.example.yaml"

VALID = """
members:
  - id: ewa
    role: domownik
    emails: [ewa@example.com]
    first_name_forms: [Ewa, Ewy]
    surname_forms: [Nowak]
  - id: jan
    role: koordynator
    emails: [jan@example.com, jan2@example.com]
    first_name_forms: [Jan, Jana]
    surname_forms: [Nowak, Nowaka]
  - id: zofia
    role: bez_konta
    first_name_forms: [Zofia]
"""


def test_example_configuration_loads():
    members = parse_household(EXAMPLE.read_text(encoding="utf-8"))
    assert [m.id for m in members] == ["ewa", "jan", "zofia"]
    assert [m.role for m in members] == [Role.DOMOWNIK, Role.KOORDYNATOR, Role.BEZ_KONTA]
    assert all(m.first_name_forms for m in members)
    assert members[1].notify_email == "jan@example.com"


def test_parse_keeps_order_and_fields():
    assert parse_household(VALID) == [
        Member("ewa", Role.DOMOWNIK, ("Ewa", "Ewy"), ("Nowak",), ("ewa@example.com",)),
        Member(
            "jan",
            Role.KOORDYNATOR,
            ("Jan", "Jana"),
            ("Nowak", "Nowaka"),
            ("jan@example.com", "jan2@example.com"),
        ),
        Member("zofia", Role.BEZ_KONTA, ("Zofia",), (), ()),
    ]


def test_display_name_defaults_to_the_first_first_name_form():
    members = parse_household(
        VALID.replace("id: zofia\n", "id: zofia\n    display_name: Babcia Zosia\n")
    )
    assert [m.name for m in members] == ["Ewa", "Jan", "Babcia Zosia"]


@pytest.mark.parametrize(
    "text, problem",
    [
        ("members: []", "members"),
        (VALID.replace("koordynator", "domownik"), "koordynator"),
        (VALID.replace("id: jan", "id: ewa"), "unique"),
        (VALID.replace("    emails: [jan@example.com, jan2@example.com]\n", ""), "needs an email"),
        (VALID.replace("jan2@example.com", "ewa@example.com"), "share an email"),
        (VALID.replace("[Jan, Jana]", "[Jan, Nowak]"), "used as a surname"),
        (VALID.replace("[Jan, Jana]", "[Jan, Ewy]"), "share a first name form"),
        (VALID.replace("[Zofia]", "[]"), "first_name_forms"),
        (VALID.replace("role: bez_konta", "role: gosc"), "role"),
        (VALID.replace("id: zofia", "id: Zofia K"), "id"),
        (VALID.replace("jan2@example.com", "jan-at-example"), "emails"),
        (VALID + "extra: 1\n", "extra"),
        ("members: [", "not valid YAML"),
    ],
)
def test_invalid_configuration(text, problem):
    with pytest.raises(ConfigError, match=problem):
        parse_household(text)


def test_error_messages_never_contain_values():
    text = VALID.replace("jan@example.com", "tajny.adres-at-example").replace(
        "[Jan, Jana]", "[Jan, Ewy]"
    )
    with pytest.raises(ConfigError) as error:
        parse_household(text)
    message = str(error.value)
    for secret in ["tajny.adres", "Ewy", "Jan,"]:
        assert secret not in message


def test_load_from_file(tmp_path):
    path = tmp_path / "household.yaml"
    path.write_text(VALID, encoding="utf-8")
    assert len(load_household({"HOUSEHOLD_FILE": str(path)})) == 3


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_household({"HOUSEHOLD_FILE": str(tmp_path / "nope.yaml")})


class FakeSecrets:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.name = payload, error, None

    def access_secret_version(self, name):
        self.name = name
        if self.error:
            raise self.error
        return SimpleNamespace(payload=SimpleNamespace(data=self.payload.encode()))


def test_load_from_secret():
    client = FakeSecrets(VALID)
    members = load_household({"HOUSEHOLD_SECRET": "projects/p/secrets/household-config"}, client)
    assert client.name == "projects/p/secrets/household-config/versions/latest"
    assert len(members) == 3


@pytest.mark.parametrize(
    "error", [gcp_exceptions.NotFound("no version"), gcp_exceptions.FailedPrecondition("disabled")]
)
def test_secret_without_version_is_a_clear_error(error):
    with pytest.raises(ConfigError, match="upload_household.sh"):
        load_household({"HOUSEHOLD_SECRET": "projects/p/secrets/x"}, FakeSecrets(error=error))


def test_no_configuration_is_a_clear_error():
    with pytest.raises(ConfigError, match="HOUSEHOLD_FILE .* or HOUSEHOLD_SECRET"):
        load_household({})


def test_file_wins_over_secret(tmp_path):
    path = tmp_path / "household.yaml"
    path.write_text(VALID, encoding="utf-8")
    client = FakeSecrets(error=AssertionError("secret must not be read"))
    environ = {"HOUSEHOLD_FILE": str(path), "HOUSEHOLD_SECRET": "projects/p/secrets/x"}
    assert len(load_household(environ, client)) == 3
