import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_private_data.py"
spec = importlib.util.spec_from_file_location("check_private_data", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

HOUSEHOLD = """
members:
  - id: jan
    role: koordynator
    emails: [jan.przyklad@example.com]
    first_name_forms: [Jan, Jana]
    surname_forms: [Przykładowy]
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "household.yaml").write_text(HOUSEHOLD, encoding="utf-8")
    (tmp_path / ".forbidden-strings").write_text(
        "# surname and street\nPrzykładowa\nul. Testowa 7\n", encoding="utf-8"
    )
    return tmp_path


def write(root: Path, name: str, text: str) -> str:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("name", ["household.yaml", "config/household.yaml", ".forbidden-strings"])
def test_private_files_are_blocked(repo, name):
    assert hook.check([name], repo) == [f"{name}: private file must not be committed"]


@pytest.mark.parametrize(
    "text",
    [
        "Pismo dla Jana.",
        "JAN PRZYKŁADOWY",
        "kontakt: jan.przyklad@example.com",
        "pani Przykładowa",
        "adres: ul. Testowa 7, Warszawa",
    ],
)
def test_household_data_is_blocked_with_line_number(repo, text):
    path = write(repo, "notes.md", "pierwsza linia\n" + text + "\n")
    assert hook.check([path], repo) == [f"{path}:2: contains household data"]


@pytest.mark.parametrize(
    "text", ["Janowiec i Janusz", "def jan_count(): pass", "Ewa Kowalska", "jan, jana (lowercase)"]
)
def test_other_text_passes(repo, text):
    assert hook.check([write(repo, "ok.py", text)], repo) == []


def test_report_never_contains_the_value(repo):
    path = write(repo, "notes.md", "Jan Przykładowy")
    report = " ".join(hook.check([path], repo))
    assert "Jan" not in report.replace(str(repo), "")


def test_binary_files_are_skipped(repo):
    path = repo / "image.png"
    path.write_bytes(b"\x89PNG\xff\xfe Jan")
    assert hook.check([str(path)], repo) == []


def test_without_private_sources_only_file_names_are_checked(tmp_path):
    path = write(tmp_path, "notes.md", "Jan")
    assert hook.check([path], tmp_path) == []
    assert hook.check(["household.yaml"], tmp_path) != []
