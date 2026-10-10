from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """Household rule. Text refers to members only by placeholders (OSOBA_1..N)."""

    id: str
    text: str
