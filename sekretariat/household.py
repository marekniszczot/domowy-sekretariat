from dataclasses import dataclass
from enum import StrEnum

# Grammatical cases of the display name besides the nominative (DT13b).
CASES = ("dopelniacz", "celownik", "biernik", "narzednik", "miejscownik", "wolacz")


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
    # How the app addresses them ("Babcia Ela"); the first first-name form if empty.
    display_name: str = ""
    # Home address as letters write it ("Lipowa 7", "Lipowej 7", "00-001"); masked as [ADRES].
    address_forms: tuple[str, ...] = ()
    # The display name in other cases (("dopelniacz", "Ewy"), ...); nominative if missing.
    name_cases: tuple[tuple[str, str], ...] = ()

    @property
    def name(self) -> str:
        return self.display_name or (self.first_name_forms[0] if self.first_name_forms else self.id)

    def name_in(self, case: str) -> str:
        return dict(self.name_cases).get(case) or self.name

    @property
    def has_account(self) -> bool:
        return self.role != Role.BEZ_KONTA

    @property
    def notify_email(self) -> str | None:
        return self.emails[0] if self.emails else None
