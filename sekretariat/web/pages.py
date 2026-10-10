"""HTML screens (T7.4): Jinja templates rendered on the server, htmx for partial updates.

Access checks stay in letters.py / access.py; this module only presents what
the `Letters` service returns for the signed-in member.

    GET /                         Moje pisma (signed out: sign-in page)
    GET /pisma/{id}               verdict card, processing steps or metadata (DR-5)
    GET /pisma/{id}/kroki         processing steps fragment, polled by htmx
    GET /pisma/{id}/strona/{n}    page photo for the greyed band (DR-1)
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response
from fastapi.templating import Jinja2Templates

from sekretariat.access import View
from sekretariat.auth import SESSION_COOKIE
from sekretariat.household import Member
from sekretariat.letters import PROCESSING, Forbidden, NotFound
from sekretariat.web import present

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()

HOME_ZONE = ZoneInfo("Europe/Warsaw")
STEPS = ["Czytam pismo", "Ukrywam dane osobowe", "Sprawdzam Wasze zasady"]
_STEP_OF_STATUS = {"received": 0, "ocr_done": 1, "masked": 2}


@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    href: str
    badge: int = 0


def tabs(user: Member, open_count: int = 0) -> list[Tab]:
    """DR-2. A bar with a single tab is not shown."""
    return [
        Tab("mine", "Moje pisma", "/", open_count),
    ]


def today() -> date:
    return datetime.now(HOME_ZONE).date()


def signed_in(request: Request) -> Member | None:
    config = request.app.state.config
    return config.sessions.member(request.cookies.get(SESSION_COOKIE), config.household)


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    context = dict(context or {})
    bar = context.pop("tabs", [])
    context["tabs"] = bar if len(bar) > 1 else []
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def login_page(request: Request, status_code: int = 200):
    config = request.app.state.config
    return render(
        request,
        "login.html",
        {"client_id": config.google_client_id, "login_uri": f"{config.base_url}/auth/google"},
        status_code,
    )


def not_found(request: Request):
    return render(request, "not_found.html", status_code=404)


@router.get("/")
def home(request: Request):
    user = signed_in(request)
    if user is None:
        return login_page(request)
    config = request.app.state.config
    letters = config.letters.mine(user)
    day = today()
    groups = [
        (g.title, [present.row(letter, True, user, config.household, day) for letter in g.letters])
        for g in present.group(letters, day)
    ]
    open_count = sum(1 for letter in letters if letter.get("state") != "closed")
    return render(
        request,
        "mine.html",
        {"groups": groups, "tabs": tabs(user, open_count), "active": "mine"},
    )


@router.get("/pisma/{letter_id}")
def letter_page(request: Request, letter_id: str):
    user = signed_in(request)
    if user is None:
        return login_page(request)
    config = request.app.state.config
    try:
        letter, level = config.letters.get(letter_id, user)
    except NotFound:
        return not_found(request)
    day = today()
    names = {m.id: m.name for m in config.household}
    if level == View.METADATA:
        due = present.deadline_date(letter)
        return render(
            request,
            "private.html",
            {
                "sender": present.sender_label(letter.get("sender_type")),
                "owner": names.get(letter.get("owner"), ""),
                "when": present.when_line(letter, day) if due else "bez terminu",
            },
        )
    if letter.get("status") in PROCESSING:
        return render(request, "processing.html", steps_context(letter))
    first = config.letters.mark_seen(letter_id, user)
    return render(request, "card.html", card(letter, user, config, day, first))


@router.get("/pisma/{letter_id}/kroki")
def letter_steps(request: Request, letter_id: str):
    user = signed_in(request)
    if user is None:
        return Response(status_code=401)
    try:
        letter, _ = request.app.state.config.letters.get(letter_id, user)
    except NotFound:
        return Response(status_code=404)
    if letter.get("status") not in PROCESSING:
        return Response(headers={"HX-Redirect": f"/pisma/{letter_id}"})
    return render(request, "_steps.html", steps_context(letter))


@router.get("/pisma/{letter_id}/strona/{number}")
def letter_page_photo(request: Request, letter_id: str, number: int):
    user = signed_in(request)
    if user is None:
        return Response(status_code=401)
    try:
        content, mime_type = request.app.state.config.letters.page(letter_id, user, number)
    except NotFound:
        return Response(status_code=404)
    except Forbidden:
        return Response(status_code=403)
    return Response(
        content, media_type=mime_type, headers={"Cache-Control": "private, max-age=3600"}
    )


def steps_context(letter: dict) -> dict:
    current = _STEP_OF_STATUS[letter["status"]]
    return {"letter_id": letter["id"], "steps": STEPS, "current": current}


def card(letter: dict, user: Member, config, day: date, first: bool) -> dict:
    """The verdict card in DR-1 order. Placeholders become names here, for display only."""
    household = config.household
    analysis = letter.get("analysis") or {}
    current = present.state(letter, day)

    def names(text: str | None) -> str:
        return present.with_names(text or "", household)

    raw = letter.get("raw_text") or ""
    spans = letter.get("quote_spans_raw") or {}

    def quote(key: str):
        span = spans.get(key)
        return present.quote_context(raw, tuple(span)) if span and raw else None

    rule = None
    if rule_id := analysis.get("rule_id"):
        rule = next((r for r in config.letters.store.rules() if r.id == rule_id), None)
    owner = next((m for m in household if m.id == letter.get("owner")), None)
    if letter.get("verdict") == "NONE":
        why = "Dlaczego nic nie trzeba robić"
    else:
        why = f"Dlaczego {owner.name}" if owner else "Dlaczego tak"

    pages = letter.get("pages") or []
    photo = bool(pages) and pages[0].get("mime", "").startswith("image/")
    delivery = letter.get("delivery_date")
    return {
        "state": current,
        "icon": present.ICON[current],
        "label": present.LABEL[current],
        "verb": names(present.verb(letter, day)),
        "when": present.when_line(letter, day),
        "sender": present.sender_label(analysis.get("sender_type")),
        "delivered": present.delivered(date.fromisoformat(delivery), day) if delivery else "",
        "confidence": present.confidence_word(letter) if analysis else None,
        "reason": present.unsure_reason(letter) if present.deadline_date(letter) else None,
        "unreadable": letter.get("status") == "unreadable",
        "summary": names(analysis.get("summary_plain_pl")),
        "consequence": quote("consequence_quote"),
        "why": why,
        "rule": names(rule.text) if rule else None,
        "quotes": [q for q in (quote("rule_trigger_quote"), quote("deadline_quote")) if q],
        "photo": f"/pisma/{letter['id']}/strona/1" if photo else None,
        "first": first,
    }
