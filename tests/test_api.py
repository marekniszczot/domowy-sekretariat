import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sekretariat.api.app import AppConfig, CurrentUser, create_app
from sekretariat.auth import SESSION_COOKIE, AuthError, Sessions, member_for_google_login
from sekretariat.blobs import MemoryBlobs
from sekretariat.household import Member, Role
from sekretariat.letters import Letters
from sekretariat.store import MemoryStore

DOM1 = Member("dom1", Role.DOMOWNIK, emails=("Dom1@Example.com", "dom1.drugi@example.com"))
KOORD = Member("koord", Role.KOORDYNATOR, emails=("koord@example.com",))
SENIOR = Member("senior", Role.BEZ_KONTA, emails=("senior@example.com",))
HOUSE = [DOM1, KOORD, SENIOR]
CLIENT_ID = "client-123.apps.googleusercontent.com"
TASKS_SA = "tasks-invoker@p.iam.gserviceaccount.com"
AUDIENCE = "https://web.example.run.app"


def fake_verify(token: str, audience: str) -> dict:
    """Tokens in tests are 'email|audience|verified|issuer'."""
    email, token_audience, verified, issuer = token.split("|")
    if token_audience != audience:
        raise ValueError("wrong audience")
    return {"email": email, "email_verified": verified == "1", "iss": issuer}


def google(email, verified="1", audience=CLIENT_ID, issuer="https://accounts.google.com"):
    return f"{email}|{audience}|{verified}|{issuer}"


# Google sign-in


@pytest.mark.parametrize("email", ["dom1@example.com", "DOM1.DRUGI@example.com"])
def test_household_member_signs_in_with_any_of_their_emails(email):
    assert member_for_google_login(google(email), CLIENT_ID, HOUSE, fake_verify) == DOM1


@pytest.mark.parametrize(
    "token",
    [
        google("stranger@example.com"),
        google("senior@example.com"),  # no account
        google("dom1@example.com", verified="0"),
        google("dom1@example.com", audience="other-client"),
        google("dom1@example.com", issuer="https://evil.example.com"),
    ],
)
def test_sign_in_refused(token):
    with pytest.raises(AuthError):
        member_for_google_login(token, CLIENT_ID, HOUSE, fake_verify)


def test_session_round_trip_and_tampering():
    sessions = Sessions("secret")
    cookie = sessions.issue(DOM1)
    assert sessions.member(cookie, HOUSE) == DOM1
    assert sessions.member(cookie + "x", HOUSE) is None
    assert Sessions("other-secret").member(cookie, HOUSE) is None
    assert sessions.member(cookie, [KOORD]) is None  # removed from the household
    assert sessions.member(None, HOUSE) is None


# Routes


@pytest.fixture
def app_and_calls():
    calls = []

    def process(letter_id, attempt):
        calls.append((letter_id, attempt))
        if letter_id == "boom":
            raise ConnectionError("down")
        return "verdict"

    config = AppConfig(
        letters=Letters(MemoryStore(), MemoryBlobs(), lambda _: None, HOUSE),
        household=HOUSE,
        sessions=Sessions("secret"),
        google_client_id=CLIENT_ID,
        verify_token=fake_verify,
        tasks_audience=AUDIENCE,
        tasks_service_account=TASKS_SA,
        process=process,
        secure_cookies=False,
    )
    app = create_app(config)

    @app.get("/whoami")
    def whoami(user=CurrentUser):
        return {"id": user.id}

    return app, calls


def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


def test_sign_in_sets_session_cookie(app_and_calls):
    app, _ = app_and_calls
    http = client(app)
    http.cookies.set("g_csrf_token", "csrf1")
    response = http.post(
        "/auth/google", data={"credential": google("dom1@example.com"), "g_csrf_token": "csrf1"}
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert (
        cookie.startswith(f"{SESSION_COOKIE}=")
        and "HttpOnly" in cookie
        and "SameSite=lax" in cookie
    )
    assert http.get("/whoami").json() == {"id": "dom1"}


def test_sign_in_needs_matching_csrf_token(app_and_calls):
    app, _ = app_and_calls
    http = client(app)
    http.cookies.set("g_csrf_token", "csrf1")
    response = http.post(
        "/auth/google", data={"credential": google("dom1@example.com"), "g_csrf_token": "other"}
    )
    assert response.status_code == 400


def test_stranger_is_refused(app_and_calls):
    app, _ = app_and_calls
    http = client(app)
    http.cookies.set("g_csrf_token", "c")
    response = http.post(
        "/auth/google", data={"credential": google("x@example.com"), "g_csrf_token": "c"}
    )
    assert response.status_code == 403
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_pages_need_a_session_and_logout_clears_it(app_and_calls):
    app, _ = app_and_calls
    http = client(app)
    assert http.get("/whoami").status_code == 401
    http.cookies.set(SESSION_COOKIE, Sessions("secret").issue(KOORD))
    assert http.get("/whoami").json() == {"id": "koord"}
    response = http.post("/logout")
    assert response.status_code == 303 and 'session=""' in response.headers["set-cookie"]


def tasks_token(email=TASKS_SA, audience=AUDIENCE):
    return {"Authorization": f"Bearer {email}|{audience}|1|https://accounts.google.com"}


def test_internal_process_runs_with_retry_count(app_and_calls):
    app, calls = app_and_calls
    response = client(app).post(
        "/internal/process/L1", headers=tasks_token() | {"X-CloudTasks-TaskRetryCount": "3"}
    )
    assert response.status_code == 200 and response.json() == {"status": "verdict"}
    assert calls == [("L1", 3)]


def test_internal_process_failure_asks_for_retry(app_and_calls):
    app, _ = app_and_calls
    response = client(app).post("/internal/process/boom", headers=tasks_token())
    assert response.status_code == 503


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        tasks_token(email="someone@p.iam.gserviceaccount.com"),
        tasks_token(audience="https://other.run.app"),
    ],
)
def test_internal_process_refuses_other_callers(app_and_calls, headers):
    app, calls = app_and_calls
    assert client(app).post("/internal/process/L1", headers=headers).status_code == 403
    assert calls == []
