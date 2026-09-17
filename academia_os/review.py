from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state import JsonStateStore


class ReviewStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


@dataclass
class ReviewItem:
    id: str
    kind: str
    title: str
    course: str | None
    details: dict[str, Any]
    status: ReviewStatus
    priority: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReviewItem":
        return cls(
            id=str(value["id"]), kind=str(value["kind"]), title=str(value["title"]), course=value.get("course"),
            details=dict(value.get("details", {})), status=ReviewStatus(value.get("status", ReviewStatus.OPEN)),
            priority=str(value.get("priority", "normal")), created_at=str(value["created_at"]), updated_at=str(value["updated_at"]),
        )


class ReviewQueue:
    def __init__(self, path: Path) -> None:
        self.store = JsonStateStore(path)

    def _items(self) -> list[ReviewItem]:
        value = self.store.read([])
        if not isinstance(value, list):
            return []
        return [ReviewItem.from_dict(item) for item in value if isinstance(item, dict) and "id" in item]

    def _save(self, items: list[ReviewItem]) -> None:
        self.store.write([asdict(item) for item in items])

    def add(self, *, kind: str, title: str, course: str | None = None, details: dict[str, Any] | None = None, priority: str = "normal") -> ReviewItem:
        now = datetime.now(timezone.utc).isoformat()
        item = ReviewItem(str(uuid4()), kind, title, course, details or {}, ReviewStatus.OPEN, priority, now, now)
        self._save(self._items() + [item])
        return item

    def list(self, *, include_resolved: bool = False) -> list[ReviewItem]:
        items = self._items()
        if not include_resolved:
            items = [item for item in items if item.status not in {ReviewStatus.RESOLVED, ReviewStatus.REJECTED}]
        return sorted(items, key=lambda item: (item.status != ReviewStatus.OPEN, item.priority, item.created_at))

    def get(self, item_id: str) -> ReviewItem:
        for item in self._items():
            if item.id == item_id:
                return item
        raise KeyError(f"review item not found: {item_id}")

    def update(self, item_id: str, *, status: ReviewStatus | str | None = None, details: dict[str, Any] | None = None) -> ReviewItem:
        items = self._items()
        for index, item in enumerate(items):
            if item.id != item_id:
                continue
            item.status = ReviewStatus(status) if status is not None else item.status
            if details is not None:
                item.details = details
            item.updated_at = datetime.now(timezone.utc).isoformat()
            items[index] = item
            self._save(items)
            return item
        raise KeyError(f"review item not found: {item_id}")
