"""Sign-in (D12) and service-to-service authentication.

    browser ── Sign in with Google (redirect mode) ──▶ POST /auth/google
        credential = Google ID token, audience = our OAuth client id
        verified e-mail on the household list ──▶ signed session cookie (httpOnly,
        Secure, SameSite=Lax, 90 days) with the member id
    Cloud Tasks ── OIDC token of the tasks service account ──▶ /internal/process/{id}

The session holds only the member id; role and e-mails come from the household
config loaded at startup, so removing someone takes effect on the next deploy or
instance restart.
"""

from collections.abc import Callable

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from itsdangerous import BadSignature, URLSafeTimedSerializer

from sekretariat.household import Member

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 90 * 24 * 3600
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

TokenVerifier = Callable[[str, str], dict]


class AuthError(Exception):
    pass


def verify_google_token(token: str, audience: str) -> dict:
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)


def member_for_google_login(
    credential: str, client_id: str, household: list[Member], verify: TokenVerifier
) -> Member:
    try:
        claims = verify(credential, client_id)
    except ValueError as error:
        raise AuthError("invalid Google token") from error
    if claims.get("iss") not in GOOGLE_ISSUERS or not claims.get("email_verified"):
        raise AuthError("unverified Google account")
    email = claims["email"].casefold()
    for member in household:
        if member.has_account and email in {e.casefold() for e in member.emails}:
            return member
    raise AuthError("not in this household")


class Sessions:
    def __init__(self, secret: str):
        self._serializer = URLSafeTimedSerializer(secret, salt="session")

    def issue(self, member: Member) -> str:
        return self._serializer.dumps({"member": member.id})

    def member(self, cookie: str | None, household: list[Member]) -> Member | None:
        if not cookie:
            return None
        try:
            data = self._serializer.loads(cookie, max_age=SESSION_MAX_AGE)
        except BadSignature:
            return None
        return next((m for m in household if m.id == data.get("member") and m.has_account), None)


def verify_tasks_request(
    authorization: str | None, audience: str, service_account: str, verify: TokenVerifier
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("missing bearer token")
    try:
        claims = verify(authorization.removeprefix("Bearer "), audience)
    except ValueError as error:
        raise AuthError("invalid OIDC token") from error
    if claims.get("email") != service_account or not claims.get("email_verified"):
        raise AuthError("unexpected caller")
