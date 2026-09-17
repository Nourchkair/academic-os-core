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

    def list(self, limit: int = 100) -> list[ActivityEvent]:
        if not self.path.is_file():
            return []
        events: list[ActivityEvent] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(ActivityEvent.from_dict(value))
            except (ValueError, TypeError, KeyError):
                continue
        return list(reversed(events))
