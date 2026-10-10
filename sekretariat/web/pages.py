"""HTML screens (T7.4): Jinja templates rendered on the server, htmx for partial updates.

Access checks stay in letters.py / access.py; this module only presents what
the `Letters` service returns for the signed-in member.

    GET /                         Moje pisma (signed out: sign-in page)
    GET /pisma/{id}               verdict card, processing steps or metadata (DR-5)
    GET /pisma/{id}/kroki         processing steps fragment, polled by htmx
    GET /pisma/{id}/strona/{n}    page photo for the greyed band (DR-1)
    GET/POST /dodaj               upload: pages, delivery date, private (DR-6, DR-7)
    POST /pisma/{id}/<akcja>      zajme-sie, przekaz, termin, zrobione, otworz, odkryj,
                                  cofnij; each redirects (POST-redirect-GET) and the
                                  next page shows the „Cofnij” bar for 8 s (DR-8)
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from sekretariat import access
from sekretariat.access import View
from sekretariat.auth import SESSION_COOKIE
from sekretariat.household import Member, Role
from sekretariat.letters import (
    MAX_PAGES,
    PROCESSING,
    Forbidden,
    InvalidUpload,
    NeedsConfirmation,
    NotFound,
)
from sekretariat.web import present

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()

HOME_ZONE = ZoneInfo("Europe/Warsaw")
STEPS = ["Czytam pismo", "Ukrywam dane osobowe", "Sprawdzam Wasze zasady"]
_STEP_OF_STATUS = {"received": 0, "ocr_done": 1, "masked": 2}
STOP_POLLING = 286  # htmx stops an `every` trigger on this status


@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    href: str
    badge: int = 0


def tabs(user: Member, open_count: int = 0) -> list[Tab]:
    """DR-2. A bar with a single tab is not shown."""
    return [
        Tab("add", "Dodaj pismo", "/dodaj"),
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
        {
            "groups": groups,
            "tabs": tabs(user, open_count),
            "active": "mine",
            "undo": undo_bar(config, user, request.query_params.get("cofnij"), "/"),
        },
    )


@router.get("/dodaj")
def upload_form(request: Request):
    user = signed_in(request)
    if user is None:
        return login_page(request)
    return upload_page(request, user)


@router.post("/dodaj")
def upload(
    request: Request,
    pages: Annotated[list[UploadFile], File()],
    when: Annotated[str, Form()] = "today",
    delivery_date: Annotated[str, Form()] = "",
    private: Annotated[bool, Form()] = False,
):
    user = signed_in(request)
    if user is None:
        return Response(status_code=401)
    day = today()
    delivered = {"today": day, "yesterday": day - timedelta(days=1)}.get(when)
    if when == "earlier":
        try:
            delivered = date.fromisoformat(delivery_date)
        except ValueError:
            delivered = None
        if delivered is not None and delivered > day:
            delivered = None
    if delivered is None:
        return upload_page(request, user, "Wybierz, kiedy przyszło pismo.", 400)
    files = [(page.file.read(), page.content_type or "") for page in pages if page.filename]
    try:
        result = request.app.state.config.letters.upload(user, files, delivered, private)
    except InvalidUpload:
        message = (
            f"Nie mogę przyjąć tych plików. Dodaj od 1 do {MAX_PAGES} zdjęć albo plików PDF, "
            "każdy do 15 MB."
        )
        return upload_page(request, user, message, 400)
    query = "?duplikat=1" if result.duplicate else ""
    return RedirectResponse(f"/pisma/{result.letter_id}{query}", status_code=303)


def upload_page(request: Request, user: Member, error: str = "", status_code: int = 200):
    return render(
        request,
        "upload.html",
        {
            "error": error,
            "max_pages": MAX_PAGES,
            "today": today().isoformat(),
            "can_be_private": user.role != Role.KOORDYNATOR,
            "tabs": tabs(user),
            "active": "add",
        },
        status_code,
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
    duplicate = request.query_params.get("duplikat") == "1"
    if letter.get("status") in PROCESSING:
        return render(request, "processing.html", steps_context(letter) | {"duplicate": duplicate})
    first = config.letters.mark_seen(letter_id, user)
    here = f"/pisma/{letter_id}"
    context = card(letter, user, config, day, first) | {
        "duplicate": duplicate,
        "failed": request.query_params.get("blad") == "1",
        "undo": undo_bar(
            config, user, letter_id if "cofnij" in request.query_params else None, here
        ),
    }
    return render(request, "card.html", context)


@router.get("/pisma/{letter_id}/kroki")
def letter_steps(request: Request, letter_id: str):
    user = signed_in(request)
    if user is None:
        return Response(status_code=STOP_POLLING)
    try:
        letter, _ = request.app.state.config.letters.get(letter_id, user)
    except NotFound:
        return Response(status_code=STOP_POLLING)
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
        "id": letter["id"],
        **actions(letter, user, config, day),
    }


# Actions (part 2): POST, then redirect to the page that shows the result.

_DONE_MESSAGES = {
    "HANDLE": "Zajmiesz się tym pismem.",
    "DONE": "Oznaczono jako zrobione.",
    "REOPEN": "Otwarto ponownie.",
    "REVEAL": "Pismo jest teraz jawne.",
    "CONFIRM_DEADLINE": "Termin zatwierdzony.",
}


def undo_bar(config, user: Member, letter_id: str | None, back: str) -> dict | None:
    if not letter_id:
        return None
    recent = config.letters.recent_action(letter_id, user)
    if recent is None:
        return None
    if recent["cause"] == "FORWARD":
        name = next((m.name for m in config.household if m.id == recent["owner"]), "")
        message = f"Przekazano: {name}."
    else:
        message = _DONE_MESSAGES.get(recent["cause"], "Zapisano.")
    return {"message": message, "action": f"/pisma/{letter_id}/cofnij", "back": back}


def _act(request: Request, letter_id: str, action, after: str):
    """Runs one Letters action for the signed-in user and redirects."""
    user = signed_in(request)
    if user is None:
        return Response(status_code=401)
    here = f"/pisma/{letter_id}"
    try:
        action(request.app.state.config.letters, user)
    except NotFound:
        return not_found(request)
    except (Forbidden, NeedsConfirmation, ValueError):
        return RedirectResponse(f"{here}?blad=1", status_code=303)
    target = f"/?cofnij={letter_id}" if after == "list" else f"{here}?cofnij=1"
    return RedirectResponse(target, status_code=303)


@router.post("/pisma/{letter_id}/zajme-sie")
def take(request: Request, letter_id: str):
    return _act(request, letter_id, lambda letters, user: letters.handle(letter_id, user), "card")


@router.post("/pisma/{letter_id}/przekaz")
def forward(
    request: Request,
    letter_id: str,
    target: Annotated[str, Form()],
    confirmed: Annotated[bool, Form()] = False,
):
    # The sheet says the target will see the whole letter (D17), so sending the form
    # from it is the confirmation for a private letter.
    return _act(
        request,
        letter_id,
        lambda letters, user: letters.forward(letter_id, user, target, confirmed),
        "list",
    )


@router.post("/pisma/{letter_id}/termin")
def confirm_deadline(request: Request, letter_id: str, deadline: Annotated[str, Form()] = ""):
    try:
        chosen = date.fromisoformat(deadline) if deadline else None
    except ValueError:
        return RedirectResponse(f"/pisma/{letter_id}?blad=1", status_code=303)
    return _act(
        request,
        letter_id,
        lambda letters, user: letters.confirm_deadline(letter_id, user, chosen),
        "card",
    )


@router.post("/pisma/{letter_id}/zrobione")
def done(request: Request, letter_id: str):
    return _act(request, letter_id, lambda letters, user: letters.done(letter_id, user), "list")


@router.post("/pisma/{letter_id}/otworz")
def reopen(request: Request, letter_id: str):
    return _act(request, letter_id, lambda letters, user: letters.reopen(letter_id, user), "card")


@router.post("/pisma/{letter_id}/odkryj")
def reveal(request: Request, letter_id: str):
    return _act(request, letter_id, lambda letters, user: letters.reveal(letter_id, user), "card")


@router.post("/pisma/{letter_id}/cofnij")
def undo(request: Request, letter_id: str, back: Annotated[str, Form()] = "/"):
    user = signed_in(request)
    if user is None:
        return Response(status_code=401)
    if not back.startswith("/") or back.startswith("//"):
        back = "/"
    try:
        request.app.state.config.letters.undo(letter_id, user)
    except Forbidden:
        pass  # too late or already undone: just show the page as it is
    return RedirectResponse(back, status_code=303)


def actions(letter: dict, user: Member, config, day: date) -> dict:
    """Which buttons the card shows; the same rules guard the POST routes."""
    household = config.household
    is_open = letter.get("state") == "open"
    can_act = access.can_act(letter, user)
    can_close = access.can_close(letter, user)
    nothing_to_do = letter.get("verdict") == "NONE"
    owns = letter.get("owner") == user.id
    primary = None
    if is_open and can_close and (nothing_to_do or (owns and letter.get("taken"))):
        primary = "done"
    elif can_act:
        primary = "take"

    sheet = None
    if can_act:
        rules = config.letters.store.rules()
        suggestion = access.forward_suggestion(letter, household, rules, user)
        rule_id = (letter.get("analysis") or {}).get("rule_id")
        rule = next((r for r in rules if r.id == rule_id), None)
        why = "prowadzi domowy sekretariat"
        if suggestion and rule and f"OSOBA_{household.index(suggestion) + 1}" in rule.text:
            why = present.with_names(rule.text, household)
        others = [m for m in access.forward_targets(household, user) if m != suggestion]
        sheet = {
            "suggestion": suggestion,
            "why": why,
            "others": others,
            "private": bool(letter.get("private")),
        }

    deadline = None
    due = present.deadline_date(letter)
    if (
        due
        and not (letter.get("deadline") or {}).get("confirmed")
        and access.can_confirm_deadline(letter, user)
    ):
        spans = letter.get("quote_spans_raw") or {}
        span = spans.get("deadline_quote")
        raw = letter.get("raw_text") or ""
        deadline = {
            "date": due.isoformat(),
            "short": present.short_date(due),
            "quote": present.quote_context(raw, tuple(span)) if span and raw else None,
        }
    coordinator = next((m for m in household if m.role == Role.KOORDYNATOR), None)
    return {
        "primary": primary,
        "sheet": sheet,
        "reopen": not is_open and can_close,
        "reveal": access.can_reveal(letter, user) and is_open,
        "coordinator": coordinator.name if coordinator else "",
        "deadline": deadline,
    }
