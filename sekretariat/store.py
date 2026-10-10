"""Letter storage: Firestore in production, memory for tests and local runs.

    letters/{id}                 one document per letter (fields: see pipeline.py)
    letters/{id}/events/{auto}   owner changes and actions (metric source)
    rules/{id}                   household rules (Rule), ids from settings/rules
    settings/rules               {"next": n}, the rule id counter (never reused)
    settings/escalation          {"entries": [...]}

Clients never touch Firestore directly (security rules deny all); everything goes
through the API with the service account.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from google.cloud import firestore

from sekretariat.guard import DEFAULT_ESCALATION
from sekretariat.rules import Rule, next_id


class Store(Protocol):
    def create_letter(self, fields: dict[str, Any]) -> str: ...
    def get_letter(self, letter_id: str) -> dict[str, Any] | None: ...
    def list_letters(self) -> list[dict[str, Any]]: ...
    def find_letter_by_hash(self, file_sha256: str) -> list[dict[str, Any]]: ...
    def update_letter(self, letter_id: str, fields: dict[str, Any]) -> None: ...
    def add_event(self, letter_id: str, event: dict[str, Any]) -> None: ...
    def events(self, letter_id: str) -> list[dict[str, Any]]: ...
    def rules(self) -> list[Rule]: ...
    def add_rule(self, text: str, display: str = "") -> str: ...
    def delete_rule(self, rule_id: str) -> None: ...
    def escalation(self) -> tuple[str, ...]: ...
    def set_escalation(self, entries: list[str]) -> None: ...


def now() -> datetime:
    return datetime.now(UTC)


class MemoryStore:
    def __init__(self, rules: list[Rule] | None = None, escalation=DEFAULT_ESCALATION):
        self.letters: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._rules = list(rules or [])
        self._rule_counter = 1
        self._escalation = tuple(escalation)

    def create_letter(self, fields):
        letter_id = uuid.uuid4().hex
        self.letters[letter_id] = {"created_at": now(), **fields}
        return letter_id

    def get_letter(self, letter_id):
        letter = self.letters.get(letter_id)
        return dict(letter) if letter is not None else None

    def list_letters(self):
        return [{"id": i, **letter} for i, letter in self.letters.items()]

    def find_letter_by_hash(self, file_sha256):
        return [
            letter for letter in self.list_letters() if letter.get("file_sha256") == file_sha256
        ]

    def update_letter(self, letter_id, fields):
        self.letters[letter_id].update(fields)

    def add_event(self, letter_id, event):
        self._events.setdefault(letter_id, []).append({"at": now(), **event})

    def events(self, letter_id):
        return list(self._events.get(letter_id, []))

    def rules(self):
        return list(self._rules)

    def add_rule(self, text, display=""):
        rule_id, self._rule_counter = next_id([r.id for r in self._rules], self._rule_counter)
        self._rules.append(Rule(rule_id, text, display))
        return rule_id

    def delete_rule(self, rule_id):
        self._rules = [r for r in self._rules if r.id != rule_id]

    def escalation(self):
        return self._escalation

    def set_escalation(self, entries):
        self._escalation = tuple(entries)


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

    def list_letters(self):
        # One household: a few hundred letters a year, no pagination needed.
        return [{"id": d.id, **d.to_dict()} for d in self._letters().stream()]

    def find_letter_by_hash(self, file_sha256):
        query = self._letters().where(
            filter=firestore.FieldFilter("file_sha256", "==", file_sha256)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]

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
        rules = (Rule(d.id, d.get("text"), d.to_dict().get("display", "")) for d in docs)
        return sorted(rules, key=_rule_order)

    def add_rule(self, text, display=""):
        rules = self._db.collection(f"{self._prefix}rules")
        counter = self._db.collection(f"{self._prefix}settings").document("rules")

        @firestore.transactional
        def create(transaction):
            snapshot = counter.get(transaction=transaction)
            current = (snapshot.to_dict() or {}).get("next", 1) if snapshot.exists else 1
            existing = [d.id for d in rules.select([]).stream()]
            rule_id, following = next_id(existing, current)
            transaction.set(counter, {"next": following})
            transaction.set(
                rules.document(rule_id), {"text": text, "display": display, "created_at": now()}
            )
            return rule_id

        return create(self._db.transaction())

    def delete_rule(self, rule_id):
        self._db.collection(f"{self._prefix}rules").document(rule_id).delete()

    def escalation(self):
        snapshot = self._db.collection(f"{self._prefix}settings").document("escalation").get()
        if not snapshot.exists:
            return DEFAULT_ESCALATION
        return tuple(snapshot.to_dict().get("entries", DEFAULT_ESCALATION))

    def set_escalation(self, entries):
        settings = self._db.collection(f"{self._prefix}settings")
        settings.document("escalation").set({"entries": list(entries)})


def _rule_order(rule: Rule):
    """R2 before R10."""
    number = rule.id[1:]
    return (0, int(number)) if number.isdigit() else (1, rule.id)
