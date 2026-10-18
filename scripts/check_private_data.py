"""Pre-commit hook: block household data from entering the public repository.

Fails when a staged file
  - is named household.yaml, or
  - contains a name form from the local household.yaml (whole word starting with a
    capital letter, as masking matches it), an e-mail or address form from it or a line from the
    local .forbidden-strings file (both any case)
    (surname, domain, street; one per line, # for comments).

Both source files are ignored by git and optional; without them only the file
name check runs. Matches are reported by file and line, never by value.

Usage (pre-commit passes staged file names): python scripts/check_private_data.py FILE...
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sekretariat.config import ConfigError, parse_household  # noqa: E402
from sekretariat.mask import name_pattern  # noqa: E402

PRIVATE_FILES = {"household.yaml", ".forbidden-strings"}


def forbidden_terms(root: Path) -> tuple[list[str], list[str]]:
    """Name forms (matched like masking does) and other strings (any case)."""
    names: list[str] = []
    other: list[str] = []
    household = root / "household.yaml"
    if household.exists():
        try:
            members = parse_household(household.read_text(encoding="utf-8"))
        except ConfigError as error:
            sys.exit(f"household.yaml: {error}")
        for member in members:
            names.extend(member.first_name_forms)
            names.extend(member.surname_forms)
            if member.display_name:
                names.append(member.display_name)
            other.extend(member.emails)
            other.extend(member.address_forms)
    extra = root / ".forbidden-strings"
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                other.append(line.strip())
    return names, other


def compile_terms(names: list[str], other: list[str]) -> re.Pattern[str] | None:
    alternatives = [name_pattern(n) for n in names]
    alternatives += [f"(?i:{re.escape(o)})" for o in other]
    if not alternatives:
        return None
    alternatives.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)")


def check(paths: list[str], root: Path = ROOT) -> list[str]:
    pattern = compile_terms(*forbidden_terms(root))
    problems = []
    for name in paths:
        path = Path(name)
        if path.name in PRIVATE_FILES:
            problems.append(f"{name}: private file must not be committed")
            continue
        if pattern is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                problems.append(f"{name}:{number}: contains household data")
    return problems


def main() -> int:
    problems = check(sys.argv[1:])
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
