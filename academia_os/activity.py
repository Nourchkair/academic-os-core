from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state import JsonStateStore


@dataclass(frozen=True)
class ActivityEvent:
    id: str
    event_type: str
    title: str
    course: str | None
    details: dict[str, Any]
    source: str | None
    confidence: str | None
    actor: str
    created_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActivityEvent":
        return cls(
            id=str(value["id"]), event_type=str(value["event_type"]), title=str(value["title"]), course=value.get("course"),
            details=dict(value.get("details", {})), source=value.get("source"), confidence=value.get("confidence"),
            actor=str(value.get("actor", "system")), created_at=str(value["created_at"]),
        )


class ActivityLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.store = JsonStateStore(self.path)

    def append(self, *, event_type: str, title: str, course: str | None = None, details: dict[str, Any] | None = None, source: str | None = None, confidence: str | None = None, actor: str = "system") -> ActivityEvent:
        event = ActivityEvent(str(uuid4()), event_type, title, course, details or {}, source, confidence, actor, datetime.now(timezone.utc).isoformat())
        self.store.append_json_line(asdict(event))
        return event

    def _read_events(self) -> list[ActivityEvent]:
        if not self.path.is_file():
            return []
        events: list[ActivityEvent] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(ActivityEvent.from_dict(value))
            except (ValueError, TypeError, KeyError):
                continue
        return events

    def list(self, limit: int = 100) -> list[ActivityEvent]:
        return list(reversed(self._read_events()[-limit:]))

    def changes_since(self, cursor: str | None = None, *, limit: int = 100) -> tuple[list[ActivityEvent], str | None]:
        """Return append-only changes after an activity id or ISO timestamp.

        Activity ids are opaque cursors.  A timestamp is accepted for agents that
        persist time checkpoints instead of ids.  Events are returned oldest-first
        so an agent can apply them in order; the cursor is the id of the last
        event returned and is safe to reuse for an idempotent paginated poll.
        """
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("activity change limit must be at least 1")
        events = self._read_events()
        start = 0
        if cursor:
            matching = next((index for index, event in enumerate(events) if event.id == cursor), None)
            if matching is not None:
                start = matching + 1
            else:
                try:
                    checkpoint = datetime.fromisoformat(cursor)
                except ValueError as exc:
                    raise ValueError("activity cursor must be an activity id or ISO timestamp") from exc
                start = next((index for index, event in enumerate(events) if datetime.fromisoformat(event.created_at) > checkpoint), len(events))
        changes = events[start : start + limit]
        return changes, (changes[-1].id if changes else cursor)
