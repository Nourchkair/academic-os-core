from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .course_identity import resolve_course_identifier
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
    action_proposal_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReviewItem":
        return cls(
            id=str(value["id"]), kind=str(value["kind"]), title=str(value["title"]), course=value.get("course"),
            details=dict(value.get("details", {})), status=ReviewStatus(value.get("status", ReviewStatus.OPEN)),
            priority=str(value.get("priority", "normal")), created_at=str(value["created_at"]), updated_at=str(value["updated_at"]),
            action_proposal_id=value.get("action_proposal_id"),
        )

def _explicit_decisions(item: ReviewItem) -> set[str]:
    choices = item.details.get("choices")
    if not isinstance(choices, list):
        return set()
    return {
        str(choice.get("id")).strip()
        for choice in choices
        if isinstance(choice, Mapping) and str(choice.get("id", "")).strip()
    }


def _course_decisions(item: ReviewItem, courses: Iterable[Mapping[str, Any]]) -> set[str]:
    decisions = {f"choose_course:{course['id']}" for course in courses if str(course.get("id", "")).strip()}
    candidates = item.details.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                course_id = candidate.get("id") or candidate.get("course_id")
                if str(course_id or "").strip():
                    decisions.add(f"choose_course:{course_id}")
    return decisions


def review_decision_ids(item: ReviewItem, courses: Iterable[Mapping[str, Any]] = ()) -> set[str]:
    """Return the stable decisions represented by the existing Review semantics."""
    courses = list(courses)
    if item.kind in {"deadline_conflict", "domain_conflict"}:
        return {"keep_current", "use_new"}
    if item.kind in {"source_verification", "reading_verification", "source_match"}:
        return {"accept_match", "keep_unverified"}
    if item.kind == "import_classification":
        decisions = {"keep_general_intake"} | _course_decisions(item, courses)
        if item.details.get("proposed_course"):
            decisions.add("use_proposed_destination")
        return decisions
    if item.kind == "course_identity_uncertainty":
        return {"keep_unassigned"} | _course_decisions(item, courses)
    if item.kind == "action_approval" or item.action_proposal_id:
        return {"approve", "reject", "approve_action", "reject_action"}
    explicit = _explicit_decisions(item)
    if explicit:
        return explicit
    return {"dismiss", "confirm"}


def validate_review_decision(item: ReviewItem, decision: str, courses: Iterable[Mapping[str, Any]] = ()) -> str:
    normalized = decision.strip() if isinstance(decision, str) else ""
    if not normalized:
        raise ValueError("review decision is required")
    if normalized.startswith("choose_course:"):
        if item.kind not in {"import_classification", "course_identity_uncertainty"}:
            raise ValueError(f"unsupported review decision for {item.kind}: {normalized}")
        requested_course = normalized.split(":", 1)[1].strip()
        if not requested_course:
            raise ValueError("choose_course decision requires a course")
        available_courses = list(courses)
        if available_courses:
            try:
                resolve_course_identifier(available_courses, requested_course)
            except (KeyError, ValueError) as exc:
                raise ValueError(f"choose_course decision requires a recognized course: {requested_course}") from exc
        elif normalized not in _course_decisions(item, ()):
            raise ValueError(f"choose_course decision requires a recognized course: {requested_course}")
        return normalized
    allowed = review_decision_ids(item, courses)
    if normalized in allowed:
        return normalized
    if item.kind == "action_approval" and (normalized.startswith("approve_") or normalized.startswith("reject_")):
        return normalized
    raise ValueError(f"unsupported review decision for {item.kind}: {normalized}")


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

    def add(self, *, kind: str, title: str, course: str | None = None, details: dict[str, Any] | None = None, priority: str = "normal", action_proposal_id: str | None = None) -> ReviewItem:
        now = datetime.now(timezone.utc).isoformat()
        item = ReviewItem(str(uuid4()), kind, title, course, details or {}, ReviewStatus.OPEN, priority, now, now, action_proposal_id)
        self.store.update([], lambda raw: [*raw, asdict(item)])
        return item

    def list(self, *, include_resolved: bool = False) -> list[ReviewItem]:
        items = self._items()
        if not include_resolved:
            items = [item for item in items if item.status not in {ReviewStatus.APPROVED, ReviewStatus.RESOLVED, ReviewStatus.REJECTED}]
        return sorted(items, key=lambda item: (item.status != ReviewStatus.OPEN, item.priority, item.created_at))

    def get(self, item_id: str) -> ReviewItem:
        for item in self._items():
            if item.id == item_id:
                return item
        raise KeyError(f"review item not found: {item_id}")

    def find_by_action_proposal_id(self, proposal_id: str) -> ReviewItem | None:
        return next((item for item in self._items() if item.action_proposal_id == proposal_id), None)

    def update(self, item_id: str, *, status: ReviewStatus | str | None = None, details: dict[str, Any] | None = None) -> ReviewItem:
        selected: list[ReviewItem] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ReviewItem.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, item in enumerate(items):
                if item.id != item_id:
                    continue
                item.status = ReviewStatus(status) if status is not None else item.status
                if details is not None:
                    item.details = details
                item.updated_at = datetime.now(timezone.utc).isoformat()
                items[index] = item
                selected.append(item)
                return [asdict(value) for value in items]
            raise KeyError(f"review item not found: {item_id}")

        self.store.update([], transition)
        return selected[0]
