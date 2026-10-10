from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    KOORDYNATOR = "koordynator"  # sees and configures everything
    DOMOWNIK = "domownik"  # has an account
    BEZ_KONTA = "bez_konta"  # masked and covered by rules, never logs in


@dataclass(frozen=True)
class Member:
    """Household member. Order in the household list defines OSOBA_1..N."""

    id: str
    role: Role = Role.DOMOWNIK
    # Every spelling of the name that may appear in a letter (inflected forms too).
    name_forms: tuple[str, ...] = ()
    email: str | None = None

    @property
    def has_account(self) -> bool:
        return self.role != Role.BEZ_KONTA
