"""Shared intake records for pasted and imported academic sources."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
INTAKE_STATUSES = frozenset({
    "candidates_found",
    "no_candidates",
    "needs_course",
    "needs_entity",
    "needs_confirmation",
    "proposed",
    "rejected",
})
CANDIDATE_STATUSES = frozenset({
    "candidate",
    "resolved",
    "needs_course",
    "needs_entity",
    "needs_confirmation",
    "proposed",
    "rejected",
    "no_change",
})
SOURCE_KINDS = frozenset({"student_report", "professor_announcement"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: Any, label: str, *, required: bool = False, maximum: int = 4000) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{label} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{label} is required")
    if "\x00" in cleaned or len(cleaned) > maximum:
        raise ValueError(f"{label} is invalid or too long")
    return cleaned or None


def date_text(value: Any, label: str = "date") -> str | None:
    cleaned = text(value, label, maximum=10)
    if cleaned is None:
        return None
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != cleaned:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return cleaned


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4()}"


@dataclass
class Intake:
    id: str
    semester: str
    course_id: str | None
    source_kind: str
    text_sha256: str
    source_path: str
    text: str
    status: str
    candidate_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)
    created_by: str = "user"
    updated_at: str = field(default_factory=now)
    dedupe_key: str = ""

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "intake id", required=True, maximum=120))
        self.semester = str(text(self.semester, "semester", required=True, maximum=40))
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported intake source kind: {self.source_kind}")
        if self.status not in INTAKE_STATUSES:
            raise ValueError(f"unsupported intake status: {self.status}")
        self.text_sha256 = str(text(self.text_sha256, "text hash", required=True, maximum=80))
        self.source_path = str(text(self.source_path, "source path", required=True, maximum=500))
        self.text = str(text(self.text, "source text", required=True, maximum=20000))
        self.dedupe_key = str(text(self.dedupe_key, "dedupe key", required=True, maximum=80))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Intake":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{key: value[key] for key in known if key in value})


@dataclass
class Candidate:
    id: str
    intake_id: str
    semester: str
    course_id: str | None
    entity_type: str
    entity_title: str | None
    field: str
    value: str | None
    value_type: str
    source_path: str
    source_locator: str | None
    source_excerpt: str | None
    source_kind: str
    confidence: str
    specificity: str
    status: str
    resolution: dict[str, Any] = field(default_factory=dict)
    proposed_change_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)
    created_by: str = "user"
    updated_at: str = field(default_factory=now)

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "candidate id", required=True, maximum=120))
        self.intake_id = str(text(self.intake_id, "intake id", required=True, maximum=120))
        self.semester = str(text(self.semester, "semester", required=True, maximum=40))
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported candidate source kind: {self.source_kind}")
        if self.status not in CANDIDATE_STATUSES:
            raise ValueError(f"unsupported candidate status: {self.status}")
        if self.field != "due_date":
            raise ValueError(f"unsupported candidate field: {self.field}")
        self.value = date_text(self.value, "candidate due date")
        self.source_path = str(text(self.source_path, "source path", required=True, maximum=500))
        self.confidence = str(text(self.confidence, "confidence", required=True, maximum=40))
        self.specificity = str(text(self.specificity, "specificity", required=True, maximum=40))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Candidate":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{key: value[key] for key in known if key in value})
