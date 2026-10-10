"""Household configuration (D11, D15). Real data never lives in the repository.

    local:      HOUSEHOLD_FILE=household.yaml           (file in .gitignore)
    Cloud Run:  HOUSEHOLD_SECRET=projects/<p>/secrets/household-config
                (uploaded with scripts/upload_household.sh)

See household.example.yaml for the format.
"""

import os
from pathlib import Path
from typing import Annotated

import yaml
from google.api_core import exceptions as gcp_exceptions
from google.cloud import secretmanager
from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator

from sekretariat.household import Member, Role


class ConfigError(Exception):
    pass


_Email = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class _MemberConfig(BaseModel, extra="forbid"):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    role: Role
    emails: list[_Email] = []
    first_name_forms: list[str] = Field(min_length=1)
    surname_forms: list[str] = []
    display_name: str = ""

    @model_validator(mode="after")
    def _email_for_accounts(self) -> "_MemberConfig":
        if self.role != Role.BEZ_KONTA and not self.emails:
            raise ValueError(f"member {self.id!r} has an account and needs an email")
        return self


class _HouseholdConfig(BaseModel, extra="forbid"):
    members: list[_MemberConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "_HouseholdConfig":
        ids = [m.id for m in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("member ids must be unique")
        if not any(m.role == Role.KOORDYNATOR for m in self.members):
            raise ValueError("household needs a koordynator")
        # Surnames may be shared (the family name); first names and e-mails may not.
        first: dict[str, str] = {}
        email: dict[str, str] = {}
        surnames = {_key(f) for m in self.members for f in m.surname_forms}
        for member in self.members:
            for form in member.first_name_forms:
                other = first.setdefault(_key(form), member.id)
                if other != member.id:
                    raise ValueError(f"members {other!r} and {member.id!r} share a first name form")
                if _key(form) in surnames:
                    raise ValueError(
                        f"member {member.id!r} has a first name form used as a surname"
                    )
            for address in member.emails:
                other = email.setdefault(address.casefold(), member.id)
                if other != member.id:
                    raise ValueError(f"members {other!r} and {member.id!r} share an email")
        return self


def _key(form: str) -> str:
    return " ".join(form.split()).casefold()


def parse_household(text: str) -> list[Member]:
    # Messages name the field, never its value: they may end up in logs.
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ConfigError("household configuration is not valid YAML") from None
    try:
        config = _HouseholdConfig.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'household'}: {e['msg']}"
            for e in error.errors(include_input=False, include_context=False)
        )
        raise ConfigError(f"invalid household configuration: {problems}") from None
    return [
        Member(
            m.id,
            m.role,
            tuple(m.first_name_forms),
            tuple(m.surname_forms),
            tuple(m.emails),
            m.display_name.strip(),
        )
        for m in config.members
    ]


def load_household(
    environ: dict[str, str] | None = None,
    secret_client: secretmanager.SecretManagerServiceClient | None = None,
) -> list[Member]:
    environ = os.environ if environ is None else environ
    if path := environ.get("HOUSEHOLD_FILE"):
        try:
            return parse_household(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ConfigError(f"HOUSEHOLD_FILE {path!r} does not exist") from error

    if secret := environ.get("HOUSEHOLD_SECRET"):
        client = secret_client or secretmanager.SecretManagerServiceClient()
        try:
            response = client.access_secret_version(name=f"{secret}/versions/latest")
        except (gcp_exceptions.NotFound, gcp_exceptions.FailedPrecondition) as error:
            raise ConfigError(
                f"secret {secret!r} has no enabled version; "
                "upload one with scripts/upload_household.sh"
            ) from error
        return parse_household(response.payload.data.decode("utf-8"))

    raise ConfigError("set HOUSEHOLD_FILE (local) or HOUSEHOLD_SECRET (Cloud Run)")
