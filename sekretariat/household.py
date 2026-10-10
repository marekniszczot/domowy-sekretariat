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
    # Every spelling that may appear in a letter, inflected forms included.
    # Masking combines first names and surnames in both orders.
    first_name_forms: tuple[str, ...] = ()
    surname_forms: tuple[str, ...] = ()
    # Any of them may sign in; reminders go to the first one.
    emails: tuple[str, ...] = ()

    @property
    def has_account(self) -> bool:
        return self.role != Role.BEZ_KONTA

    @property
    def notify_email(self) -> str | None:
        return self.emails[0] if self.emails else None
