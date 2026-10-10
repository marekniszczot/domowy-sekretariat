"""Letter storage: Firestore in production, memory for tests and local runs.

    letters/{id}                 one document per letter (fields: see pipeline.py)
    letters/{id}/events/{auto}   owner changes and actions (metric source)
    rules/{id}                   household rules (Rule)
    settings/escalation          {"entries": [...]}

Clients never touch Firestore directly (security rules deny all); everything goes
through the API with the service account.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from google.cloud import firestore

from sekretariat.guard import DEFAULT_ESCALATION
from sekretariat.rules import Rule


class Store(Protocol):
    def create_letter(self, fields: dict[str, Any]) -> str: ...
    def get_letter(self, letter_id: str) -> dict[str, Any] | None: ...
    def update_letter(self, letter_id: str, fields: dict[str, Any]) -> None: ...
    def add_event(self, letter_id: str, event: dict[str, Any]) -> None: ...
    def events(self, letter_id: str) -> list[dict[str, Any]]: ...
    def rules(self) -> list[Rule]: ...
    def escalation(self) -> tuple[str, ...]: ...


def now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    def __init__(self, rules: list[Rule] | None = None, escalation=DEFAULT_ESCALATION):
        self.letters: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._rules = list(rules or [])
        self._escalation = tuple(escalation)

    def create_letter(self, fields):
        letter_id = uuid.uuid4().hex
        self.letters[letter_id] = {"created_at": now(), **fields}
        return letter_id

    def get_letter(self, letter_id):
        letter = self.letters.get(letter_id)
        return dict(letter) if letter is not None else None

    def update_letter(self, letter_id, fields):
        self.letters[letter_id].update(fields)

    def add_event(self, letter_id, event):
        self._events.setdefault(letter_id, []).append({"at": now(), **event})

    def events(self, letter_id):
        return list(self._events.get(letter_id, []))

    def rules(self):
        return list(self._rules)

    def escalation(self):
        return self._escalation


class FirestoreStore:
    def __init__(self, client: firestore.Client, prefix: str = ""):
        self._db = client
        self._prefix = prefix  # lets integration tests use their own collections

    def _letters(self):
        return self._db.collection(f"{self._prefix}letters")

    def create_letter(self, fields):
        ref = self._letters().document()
        ref.set({"created_at": firestore.SERVER_TIMESTAMP, **fields})
        return ref.id

    def get_letter(self, letter_id):
        snapshot = self._letters().document(letter_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def update_letter(self, letter_id, fields):
        self._letters().document(letter_id).update(fields)

    def add_event(self, letter_id, event):
        events = self._letters().document(letter_id).collection("events")
        events.add({"at": firestore.SERVER_TIMESTAMP, **event})

    def events(self, letter_id):
        events = self._letters().document(letter_id).collection("events")
        return [e.to_dict() for e in events.order_by("at").stream()]

    def rules(self):
        docs = self._db.collection(f"{self._prefix}rules").stream()
        return sorted((Rule(d.id, d.to_dict()["text"]) for d in docs), key=lambda r: r.id)

    def escalation(self):
        snapshot = self._db.collection(f"{self._prefix}settings").document("escalation").get()
        if not snapshot.exists:
            return DEFAULT_ESCALATION
        return tuple(snapshot.to_dict().get("entries", DEFAULT_ESCALATION))
