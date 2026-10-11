"""E-mail layout shared by reminders and notices: plain text plus simple HTML.

Only metadata goes in (D7): callers pass sender labels, dates in words and links,
never letter content. Colors are DESIGN.md tokens; no images, no web fonts.
"""

import html
from dataclasses import dataclass
from datetime import date

from sekretariat.mailer import Email
from sekretariat.web.present import countdown, on_date, until_date

SIGNATURE = "Domowy Sekretariat"
CONTENT_IN_APP = "Treść pism jest tylko w aplikacji, po zalogowaniu."

_INK = "#1D2A5C"
_MUTED = "#5B6478"
_RULE = "#DDE0E6"
_URGENT = "#B3261E"
_GROUND = "#F4F5F7"
_FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Item:
    title: str  # sender label
    line: str  # deadline in words, or what happened
    link: str
    note: str = ""
    urgent: bool = False  # ▲ and red


def compose(subject: str, intro: str, items: list[Item], outro: str) -> Email:
    text_items = []
    html_items = []
    for item in items:
        line = f"▲ {item.line}" if item.urgent else item.line
        text_items.append("\n".join(filter(None, [f"{item.title}: {line}", item.note, item.link])))
        color = _URGENT if item.urgent else _INK
        html_items.append(
            f'<div style="border-top:1px solid {_RULE};padding:16px 0;">'
            f'<p style="margin:0;font-weight:700;">{html.escape(item.title)}</p>'
            f'<p style="margin:4px 0 0;color:{color};font-weight:700;">{html.escape(line)}</p>'
            + (
                f'<p style="margin:4px 0 0;color:{_MUTED};">{html.escape(item.note)}</p>'
                if item.note
                else ""
            )
            + f'<p style="margin:12px 0 0;"><a href="{html.escape(item.link)}" '
            f'style="display:inline-block;background:{_INK};color:#FFFFFF;'
            f'text-decoration:none;font-weight:700;padding:14px 20px;border-radius:6px;">'
            "Otwórz pismo</a></p></div>"
        )

    text = "\n\n".join([intro, *text_items, outro, SIGNATURE]) + "\n"
    body = (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8"></head>'
        f'<body style="margin:0;background:{_GROUND};">'
        f'<div style="max-width:560px;margin:0 auto;padding:24px 16px;font-family:{_FONT};'
        f'font-size:18px;line-height:1.5;color:{_INK};">'
        f'<p style="margin:0 0 16px;">{html.escape(intro)}</p>'
        + "".join(html_items)
        + f'<p style="margin:16px 0 0;border-top:1px solid {_RULE};padding-top:16px;'
        f'font-size:15px;color:{_MUTED};">{html.escape(outro)}</p>'
        f'<p style="margin:8px 0 0;font-size:15px;color:{_MUTED};">{SIGNATURE}</p>'
        "</div></body></html>"
    )
    return Email(subject, text, body)


def deadline_words(due: date, confirmed: bool, day: date) -> str:
    """As on the letter card: „jutro · najpóźniej do wtorku, 13 października”."""
    if due < day:
        return f"termin minął {on_date(due, day)}"
    until = until_date(due, day)
    if not confirmed:
        until = f"najpóźniej {until}"
    return f"{countdown(due, day)} · {until}"


def plural(count: int, one: str, few: str, many: str) -> str:
    """Polish noun form for `count`: 1 pismo, 2 pisma, 5 pism, 22 pisma."""
    if count == 1:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many
