"""Letter operations for the web layer, with access checks (access.py).

Every action records an event (metric source) and keeps `last_action` on the
letter with the fields as they were, so „Cofnij” (DR-8) restores exactly that.
`taken` says the current owner clicked „Zajmę się tym”; forwarding clears it, so
the new owner decides for themselves. Forwarding also records `assigned`, from
which the new owner gets an e-mail (notices.py, DR-12).
A letter the user may not see raises NotFound, so its existence never leaks.
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sekretariat import access
from sekretariat.access import View
from sekretariat.blobs import BlobMissing, Blobs
from sekretariat.household import Member, Role
from sekretariat.notices import FORWARD, assigned
from sekretariat.owners import Cause, act
from sekretariat.store import Store, now

ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
MAX_PAGES = 10
MAX_PAGE_BYTES = 15 * 1024 * 1024
UNDO_WINDOW = timedelta(seconds=60)  # the UI offers 8 s; the rest absorbs latency
PROCESSING = {"received", "ocr_done", "masked"}
FINISHED = {"verdict", "failed", "unreadable"}
METADATA_FIELDS = ("status", "deadline", "owner", "state", "private", "created_at")
UNDOABLE = ("owner", "state", "private", "deadline", "taken")


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class NeedsConfirmation(Exception):
    """Forwarding a private letter: the target will see its content (D17)."""


class InvalidUpload(Exception):
    pass


@dataclass(frozen=True)
class Upload:
    letter_id: str
    duplicate: bool


@dataclass
class Letters:
    store: Store
    blobs: Blobs
    enqueue: Callable[[str], None]
    household: list[Member]
    # Immediate reminder when a corrected deadline is close (D3); must not raise.
    remind: Callable[[str], None] = lambda letter_id: None
    # „Masz nowe pismo do ogarnięcia” for the member (DR-12); must not raise.
    notify: Callable[[str], None] = lambda member_id: None

    # Reading

    def get(self, letter_id: str, user: Member) -> tuple[dict, View]:
        letter = self.store.get_letter(letter_id)
        if letter is None:
            raise NotFound(letter_id)
        level = access.view_level(letter, user)
        if level == View.NONE:
            raise NotFound(letter_id)
        return project({"id": letter_id, **letter}, level), level

    def mine(self, user: Member) -> list[dict]:
        """Letters the user owns, plus own uploads still being processed."""
        letters = [
            letter
            for letter in self.store.list_letters()
            if letter.get("owner") == user.id
            or (
                letter.get("uploaded_by") == user.id
                and letter.get("status") not in {"verdict", "failed"}
            )
        ]
        return sorted(letters, key=_newest_first)

    def page(self, letter_id: str, user: Member, number: int) -> tuple[bytes, str]:
        """Photo of page `number` (from 1); NotFound once the lifecycle rule deleted it."""
        letter = self._letter(letter_id, user, access.can_read)
        pages = letter.get("pages") or []
        if not 1 <= number <= len(pages):
            raise NotFound(letter_id)
        try:
            return self.blobs.get(pages[number - 1]["path"])
        except BlobMissing:
            raise NotFound(letter_id) from None

    def mark_seen(self, letter_id: str, user: Member) -> bool:
        """True on the user's first look at a finished letter: the stamp lands then
        (DESIGN.md, Motion) and the „nowe” dot goes away."""
        letter = self._letter(letter_id, user, access.can_read)
        seen = letter.get("seen_by") or []
        if letter.get("status") not in FINISHED or user.id in seen:
            return False
        self.store.update_letter(letter_id, {"seen_by": [*seen, user.id]})
        return True

    def household_letters(self, user: Member) -> list[tuple[dict, View]]:
        """„Wszystkie”: coordinator only, private letters as metadata."""
        if user.role != Role.KOORDYNATOR:
            raise Forbidden("only the coordinator sees all letters")
        result = []
        for letter in sorted(self.store.list_letters(), key=_newest_first):
            level = access.view_level(letter, user)
            result.append((project(letter, level), level))
        return result

    # Upload

    def upload(
        self, user: Member, pages: list[tuple[bytes, str]], delivery_date: date, private: bool
    ) -> Upload:
        if not user.has_account:
            raise Forbidden("no account")
        if not 1 <= len(pages) <= MAX_PAGES:
            raise InvalidUpload(f"between 1 and {MAX_PAGES} pages")
        for content, mime_type in pages:
            if mime_type not in ALLOWED_TYPES:
                raise InvalidUpload(f"unsupported type {mime_type}")
            if not 0 < len(content) <= MAX_PAGE_BYTES:
                raise InvalidUpload("page too large or empty")

        digest = hashlib.sha256(
            b"".join(hashlib.sha256(content).digest() for content, _ in pages)
        ).hexdigest()
        for existing in self.store.find_letter_by_hash(digest):
            if access.view_level(existing, user) != View.NONE:
                if existing.get("status") == "received":
                    self.enqueue(existing["id"])  # the first enqueue may have failed
                return Upload(existing["id"], duplicate=True)

        folder = f"uploads/{uuid.uuid4().hex}"
        stored = []
        for number, (content, mime_type) in enumerate(pages, start=1):
            path = f"{folder}/p{number}.{ALLOWED_TYPES[mime_type]}"
            self.blobs.put(path, content, mime_type)
            stored.append({"path": path, "mime": mime_type})
        letter_id = self.store.create_letter(
            {
                "status": "received",
                "uploaded_by": user.id,
                "delivery_date": delivery_date.isoformat(),
                "upload_private": private,
                "pages": stored,
                "file_sha256": digest,
            }
        )
        self.enqueue(letter_id)
        return Upload(letter_id, duplicate=False)

    # Actions

    def handle(self, letter_id: str, user: Member) -> None:
        """„Zajmę się tym”."""
        letter = self._letter(letter_id, user, access.can_act)
        event = act(self.household, letter["owner"], Cause.HANDLE, user.id)
        changes = {"owner": event.owner, "taken": True}
        self._apply(letter_id, letter, user, Cause.HANDLE.value, changes)

    def forward(self, letter_id: str, user: Member, target: str, confirmed: bool = False) -> None:
        """„Przekaż”."""
        letter = self._letter(letter_id, user, access.can_act)
        if letter.get("private") and not confirmed:
            raise NeedsConfirmation(target)
        event = act(self.household, letter["owner"], Cause.FORWARD, user.id, target)
        changes = {
            "owner": event.owner,
            "taken": False,
            "assigned": assigned(event.owner, user.id, now(), FORWARD),
        }
        self._apply(letter_id, letter, user, Cause.FORWARD.value, changes)
        if event.owner != user.id:
            self.notify(event.owner)

    def confirm_deadline(self, letter_id: str, user: Member, deadline: date | None = None) -> None:
        letter = self._letter(letter_id, user, access.can_confirm_deadline)
        confirmed = dict(letter["deadline"], confirmed=True)
        if deadline is not None:
            confirmed["date"] = deadline.isoformat()
        self._apply(letter_id, letter, user, "CONFIRM_DEADLINE", {"deadline": confirmed})
        self.remind(letter_id)

    def done(self, letter_id: str, user: Member) -> None:
        letter = self._letter(letter_id, user, access.can_close)
        self._apply(letter_id, letter, user, "DONE", {"state": "closed"})

    def reopen(self, letter_id: str, user: Member) -> None:
        letter = self._letter(letter_id, user, access.can_close)
        self._apply(letter_id, letter, user, "REOPEN", {"state": "open"})

    def reveal(self, letter_id: str, user: Member) -> None:
        """„Odkryj”: the coordinator may now see the content (DR-5)."""
        letter = self._letter(letter_id, user, access.can_reveal)
        self._apply(letter_id, letter, user, "REVEAL", {"private": False})

    def recent_action(self, letter_id: str, user: Member) -> dict | None:
        """The user's own action that „Cofnij” can still undo: {cause, owner}.

        No view check: after forwarding, the user may no longer see the letter but
        still undoes their own click. Only the owner they chose is revealed."""
        letter = self.store.get_letter(letter_id)
        last = (letter or {}).get("last_action")
        if not last or last["actor"] != user.id or now() - last["at"] > UNDO_WINDOW:
            return None
        return {"cause": last["cause"], "owner": letter.get("owner")}

    def undo(self, letter_id: str, user: Member) -> None:
        if self.recent_action(letter_id, user) is None:
            raise Forbidden("nothing to undo")
        last = self.store.get_letter(letter_id)["last_action"]
        self.store.update_letter(letter_id, {**last["before"], "last_action": None})
        self.store.add_event(
            letter_id, {"cause": "UNDO", "undoes": last["cause"], "actor": user.id}
        )

    # Helpers

    def _letter(self, letter_id: str, user: Member, allowed) -> dict:
        letter = self.store.get_letter(letter_id)
        if letter is None or access.view_level(letter, user) == View.NONE:
            raise NotFound(letter_id)
        if not allowed(letter, user):
            raise Forbidden(allowed.__name__)
        return letter

    def _apply(self, letter_id: str, letter: dict, user: Member, cause: str, changes: dict) -> None:
        before = {key: letter.get(key) for key in UNDOABLE}
        self.store.add_event(
            letter_id,
            {
                "cause": cause,
                "actor": user.id,
                "owner": changes.get("owner", letter.get("owner")),
                "previous": letter.get("owner"),
            },
        )
        last = {"actor": user.id, "cause": cause, "at": now(), "before": before}
        self.store.update_letter(letter_id, {**changes, "last_action": last})


def project(letter: dict, level: View) -> dict:
    """What the user may see. METADATA: no content, no verdict (DR-5)."""
    if level == View.FULL:
        return letter
    analysis = letter.get("analysis") or {}
    return {
        "id": letter.get("id"),
        "sender_type": analysis.get("sender_type"),
        **{key: letter.get(key) for key in METADATA_FIELDS},
    }


def _newest_first(letter: dict):
    created = letter.get("created_at")
    return -created.timestamp() if created else 0
