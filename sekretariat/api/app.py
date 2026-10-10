"""FastAPI application: sign-in, session, internal processing endpoint.

The HTML screens (T7.4) are added on top of `create_app` and use `current_user`
and the `Letters` service; every access check lives in letters.py / access.py.
"""

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sekretariat.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    AuthError,
    Sessions,
    TokenVerifier,
    member_for_google_login,
    verify_tasks_request,
)
from sekretariat.household import Member
from sekretariat.letters import Letters

log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    letters: Letters
    household: list[Member]
    sessions: Sessions
    google_client_id: str
    verify_token: TokenVerifier
    tasks_audience: str
    tasks_service_account: str
    process: Callable[[str, int], str]
    secure_cookies: bool = True


def create_app(config: AppConfig) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/auth/google")
    def google_login(request: Request, credential: str = Form(...), g_csrf_token: str = Form(...)):
        # Sign in with Google (redirect mode) posts the same token in a cookie and the body.
        cookie_token = request.cookies.get("g_csrf_token", "")
        if not cookie_token or not hmac.compare_digest(cookie_token, g_csrf_token):
            raise HTTPException(400, "CSRF token mismatch")
        try:
            member = member_for_google_login(
                credential, config.google_client_id, config.household, config.verify_token
            )
        except AuthError as error:
            log.info("sign-in refused: %s", error)
            raise HTTPException(403, "not in this household") from None
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            config.sessions.issue(member),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=config.secure_cookies,
            samesite="lax",
        )
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.post("/internal/process/{letter_id}")
    def process_letter(
        letter_id: str,
        authorization: str | None = Header(default=None),
        x_cloudtasks_taskretrycount: int = Header(default=0),
    ):
        try:
            verify_tasks_request(
                authorization,
                config.tasks_audience,
                config.tasks_service_account,
                config.verify_token,
            )
        except AuthError as error:
            log.warning("internal call refused: %s", error)
            raise HTTPException(403, "forbidden") from None
        try:
            status = config.process(letter_id, x_cloudtasks_taskretrycount)
        except Exception as error:  # Cloud Tasks retries on any non-2xx
            log.warning("letter %s: %s, will retry", letter_id, type(error).__name__)
            return JSONResponse({"retry": True}, status_code=503)
        return {"status": status}

    return app


def current_user(request: Request) -> Member:
    config: AppConfig = request.app.state.config
    member = config.sessions.member(request.cookies.get(SESSION_COOKIE), config.household)
    if member is None:
        raise HTTPException(401, "sign in")
    return member


CurrentUser = Depends(current_user)
