"""The evaluation set: synthetic letters with the outcome the system should reach.

eval/household.fixture.yaml   fictional household (OSOBA_1..N)
eval/regulamin.fixture.yaml   rules as the model sees them, ids never reused
eval/cases/*.yaml             letters; each one:
    id, text, delivery_date, tags (injection, relative, escalation, ...),
    expected: verdict (after the guard), rule_id (the model's), deadline (computed),
              addressee (member id or null), sender_type
"""

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from sekretariat.config import parse_household
from sekretariat.household import Member
from sekretariat.llm import SenderType, Verdict
from sekretariat.rules import Rule

ROOT = Path(__file__).resolve().parents[2] / "eval"


class Expected(BaseModel, extra="forbid"):
    verdict: Verdict
    rule_id: str | None
    deadline: date | None
    addressee: str | None
    sender_type: SenderType


class Case(BaseModel, extra="forbid"):
    id: str
    text: str
    delivery_date: date
    tags: tuple[str, ...] = ()
    expected: Expected


class _Rules(BaseModel, extra="forbid"):
    class _Rule(BaseModel, extra="forbid"):
        id: str
        text: str

    rules: list[_Rule] = Field(min_length=1)


def load_cases(directory: Path = ROOT / "cases") -> list[Case]:
    cases = [
        Case.model_validate(item)
        for path in sorted(directory.glob("*.yaml"))
        for item in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]
    ids = [case.id for case in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
    return cases


def load_rules(path: Path = ROOT / "regulamin.fixture.yaml") -> list[Rule]:
    data = _Rules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return [Rule(rule.id, rule.text) for rule in data.rules]


def load_household(path: Path = ROOT / "household.fixture.yaml") -> list[Member]:
    return parse_household(path.read_text(encoding="utf-8"))
