"""HTML screens (T7.4): Jinja templates rendered on the server, htmx for partial updates.

Access checks stay in letters.py / access.py; this module only presents what
the `Letters` service returns for the signed-in member.
"""

from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from sekretariat.auth import SESSION_COOKIE
from sekretariat.household import Member

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


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


@router.get("/")
def home(request: Request):
    user = signed_in(request)
    if user is None:
        return login_page(request)
    letters = request.app.state.config.letters.mine(user)
    open_count = sum(1 for letter in letters if letter.get("state") != "closed")
    return render(
        request,
        "mine.html",
        {"letters": letters, "tabs": tabs(user, open_count), "active": "mine"},
    )
