"""Deadline from the model's analysis, computed conservatively (D10, D8).

Any error must land earlier than the real deadline, never later:
  - the delivery day is not counted: "14 dni od doręczenia" delivered on the 1st -> 15th;
  - always calendar days, also for "dni robocze", and no shift from a Saturday,
    Sunday or holiday to the next working day (the law shifts it later);
  - weeks are 7 days; months are calendar months, clamped to the month end
    (31 Jan + 1 month -> 28 Feb, as in art. 112 KC);
  - the model's idea of the anchor is not trusted. Delivery is the anchor only
    when the verified deadline quote says so (doręczenie, otrzymanie, odbiór).
    Otherwise the earlier of letter date and delivery date is used; without a
    letter date, delivery is assumed and the basis says so.

    ABSOLUTE ───────────────────────────────▶ stated date          STATED
    RELATIVE ─┬─ quote names delivery ──────▶ delivery + n         DELIVERY
              ├─ letter date known ─────────▶ min(letter, delivery) + n  LETTER_DATE
              └─ otherwise ─────────────────▶ delivery + n         ASSUMED_DELIVERY

Every deadline, stated or computed, still needs a human to confirm it.
The caller passes the upload date as delivery date when the user gave none.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sekretariat.llm import DeadlineType, DeadlineUnit, LetterAnalysis

_DELIVERY_WORDS = re.compile(r"(?<!\w)(doręcz|otrzyma|odbior|odebra)", re.IGNORECASE)


class Basis(StrEnum):
    STATED = "STATED"
    DELIVERY = "DELIVERY"
    LETTER_DATE = "LETTER_DATE"
    ASSUMED_DELIVERY = "ASSUMED_DELIVERY"


@dataclass(frozen=True)
class Deadline:
    date: date
    basis: Basis

    @property
    def computed(self) -> bool:
        """Shown as „najpóźniej (wyliczone ostrożnie)”."""
        return self.basis != Basis.STATED


def compute_deadline(analysis: LetterAnalysis, delivery_date: date) -> Deadline | None:
    if analysis.deadline_type == DeadlineType.NONE:
        return None
    if analysis.deadline_type == DeadlineType.ABSOLUTE:
        return Deadline(analysis.deadline_date, Basis.STATED)

    if _DELIVERY_WORDS.search(analysis.deadline_quote or ""):
        anchor, basis = delivery_date, Basis.DELIVERY
    elif analysis.letter_date is not None:
        anchor, basis = min(analysis.letter_date, delivery_date), Basis.LETTER_DATE
    else:
        anchor, basis = delivery_date, Basis.ASSUMED_DELIVERY
    return Deadline(
        add(anchor, analysis.deadline_relative_amount, analysis.deadline_relative_unit), basis
    )


def add(start: date, amount: int, unit: DeadlineUnit) -> date:
    if unit == DeadlineUnit.DAYS:
        return start + timedelta(days=amount)
    if unit == DeadlineUnit.WEEKS:
        return start + timedelta(weeks=amount)
    month_index = start.month - 1 + amount
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
