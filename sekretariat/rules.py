"""Household rules (DR-17). The model only ever sees placeholders, never names.

    editor: one sentence + who handles it (optional) + sender type (optional)
        "Rachunki za prąd ogarnia Ewa."  + Ewa + ENERGIA
    text (to the model):  "Rachunki za prąd ogarnia OSOBA_1. Dotyczy: Dostawca energii."
    display (to people):  "Rachunki za prąd ogarnia Ewa. Dotyczy: Dostawca energii."

`display` keeps the sentence as written, because placeholders lose the Polish
case ("do OSOBA_2" cannot become "do Jana" again).

IDs are R1, R2, ... from a counter and never reused after a rule is deleted
(R3-9), so a verdict always points at the rule that made it.
"""

from dataclasses import dataclass

from sekretariat.household import Member

MAX_SENTENCE = 300


@dataclass(frozen=True)
class Rule:
    """Household rule. Text refers to members only by placeholders (OSOBA_1..N)."""

    id: str
    text: str
    display: str = ""  # as written, with names; empty for rules added by hand


class InvalidRule(Exception):
    pass


def compose(
    sentence: str,
    member: Member | None,
    sender_label: str | None,
    household: list[Member],
) -> tuple[str, str]:
    """(text for the model, display for people)."""
    from sekretariat.mask import mask

    sentence = " ".join(sentence.split())
    if not sentence:
        raise InvalidRule("empty")
    if len(sentence) > MAX_SENTENCE:
        raise InvalidRule("too long")
    if sentence[-1] not in ".!?":
        sentence += "."
    text, display = mask(sentence, [], household).masked_text, sentence
    if member is not None:
        placeholder = f"OSOBA_{household.index(member) + 1}"
        if placeholder not in text:
            text += f" Zajmuje się tym {placeholder}."
            display += f" Zajmuje się tym {member.name}."
    if sender_label:
        text += f" Dotyczy: {sender_label}."
        display += f" Dotyczy: {sender_label}."
    return text, display


def next_id(existing: list[str], counter: int) -> tuple[str, int]:
    """The next rule id and the new counter; never below an id already in use."""
    used = [int(i[1:]) for i in existing if i[:1] == "R" and i[1:].isdigit()]
    number = max([counter, *(n + 1 for n in used)])
    return f"R{number}", number + 1
