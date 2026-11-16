"""Validation and serialization for knowledge assertions and ChangeSets."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
KNOWLEDGE_RELATIVE_PATH = ".academia/knowledge"

SOURCE_KINDS = frozenset({
    "original_document",
    "student_report",
    "professor_announcement",
    "ai_extraction",
    "verified_external",
    "legacy_record",
    "external_edit",
    "system_projection",
})
VERIFICATION_STATES = frozenset({"verified", "corroborated", "unverified", "disputed"})
CONFIDENCE_STATES = frozenset({"current-confirmed", "likely", "unverified", "historical"})
SPECIFICITY_STATES = frozenset({"exact", "partial", "approximate", "unknown"})
ASSERTION_STATUSES = frozenset({"candidate", "active", "superseded", "rejected", "retracted"})
LINK_MODES = frozenset({"mirror_deadline", "related"})
LINK_STATUSES = frozenset({"active", "paused", "removed"})
OPERATION_TYPES = frozenset({"assessment.set_deadline", "task.set_due", "study_plan.reschedule"})
OPERATION_STATUSES = frozenset({
    "proposed",
    "approved",
    "executing",
    "verified",
    "failed",
    "blocked",
    "conflict",
    "skipped",
    "recovery_required",
    "reversed",
    "already_reversed",
    "reversal_conflict",
    "irreversible",
})
CHANGESET_STATUSES = frozenset({
    "draft",
    "proposed",
    "approved",
    "executing",
    "verified",
    "partially_applied",
    "failed",
    "cancelled",
    "reverted",
    "partially_reverted",
    "reversal_conflict",
    "superseded",
})
AGENT_ACTOR_PREFIX = "agent:"
AGENT_CHANNELS = frozenset({"mcp", "assistant", "internal"})
USER_ACTORS = frozenset({"user", "student"})
USER_CHANNELS = frozenset({"dashboard", "cli_user"})
DEFAULT_MAX_ATTEMPTS = 3


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


def date_text(value: Any, label: str = "date") -> str:
    cleaned = text(value, label, required=True, maximum=10)
    try:
        parsed = date.fromisoformat(str(cleaned))
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != cleaned:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return str(cleaned)


def normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4()}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _pick(value: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


@dataclass
class Evidence:
    id: str
    source: str
    source_kind: str
    captured_at: str
    source_path: str | None = None
    source_url: str | None = None
    locator: str | None = None
    excerpt: str | None = None
    sha256: str | None = None
    provenance: str = "USER-CREATED"
    authority: str = "unknown"
    verification: str = "unverified"

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "evidence id", required=True, maximum=120))
        self.source = str(text(self.source, "evidence source", required=True, maximum=500))
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported evidence source_kind: {self.source_kind}")
        self.captured_at = str(text(self.captured_at, "captured_at", required=True, maximum=80))
        if self.verification not in VERIFICATION_STATES:
            raise ValueError(f"unsupported evidence verification: {self.verification}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Evidence":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**_pick(value, known))


@dataclass
class Assertion:
    id: str
    subject_type: str
    subject_id: str
    field: str
    value: Any
    value_type: str
    source_kind: str
    authority_scope: list[str]
    specificity: str
    verification: str
    confidence: str
    observed_at: str
    created_at: str
    created_by: str
    status: str = "active"
    updated_at: str | None = None
    published_at: str | None = None
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    applied_change_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    subject_label: str | None = None
    legacy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "assertion id", required=True, maximum=120))
        self.subject_type = str(text(self.subject_type, "subject type", required=True, maximum=40))
        self.subject_id = str(text(self.subject_id, "subject id", required=True, maximum=200))
        self.field = str(text(self.field, "field", required=True, maximum=80))
        self.value_type = str(text(self.value_type, "value_type", required=True, maximum=20))
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported assertion source_kind: {self.source_kind}")
        if self.specificity not in SPECIFICITY_STATES:
            raise ValueError(f"unsupported assertion specificity: {self.specificity}")
        if self.verification not in VERIFICATION_STATES:
            raise ValueError(f"unsupported assertion verification: {self.verification}")
        if self.confidence not in CONFIDENCE_STATES:
            raise ValueError(f"unsupported assertion confidence: {self.confidence}")
        if self.status not in ASSERTION_STATUSES:
            raise ValueError(f"unsupported assertion status: {self.status}")
        if not isinstance(self.authority_scope, list) or not all(isinstance(item, str) and item.strip() for item in self.authority_scope):
            raise ValueError("authority_scope must be a list of field patterns")
        if not isinstance(self.evidence_ids, list) or not all(isinstance(item, str) and item.strip() for item in self.evidence_ids):
            raise ValueError("evidence_ids must be a list of evidence ids")
        if self.field == "due_date":
            self.value = date_text(self.value, "assertion due_date")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Assertion":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**_pick(value, known))


@dataclass
class TaskLink:
    id: str
    course_id: str
    assessment_id: str
    task_id: str
    mode: str
    status: str
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    last_synced_due_date: str | None = None
    paused_by_change_id: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "link id", required=True, maximum=120))
        self.course_id = str(text(self.course_id, "course id", required=True, maximum=200))
        self.assessment_id = str(text(self.assessment_id, "assessment id", required=True, maximum=200))
        self.task_id = str(text(self.task_id, "task id", required=True, maximum=120))
        if self.mode not in LINK_MODES:
            raise ValueError(f"unsupported task link mode: {self.mode}")
        if self.status not in LINK_STATUSES:
            raise ValueError(f"unsupported task link status: {self.status}")
        if self.last_synced_due_date is not None:
            self.last_synced_due_date = date_text(self.last_synced_due_date, "last_synced_due_date")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskLink":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**_pick(value, known))


@dataclass
class Operation:
    id: str
    type: str
    target: dict[str, Any]
    before: Any
    after: Any
    depends_on: list[str] = field(default_factory=list)
    required: bool = True
    default_selected: bool = True
    reversible: bool = True
    sync_basis: str | None = None
    skip_effect: str | None = None
    expected_revision: str | None = None
    idempotency_key: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "proposed"
    attempts: int = 0
    last_error: str | None = None
    error_class: str | None = None
    result: dict[str, Any] | None = None
    label: str | None = None
    target_title: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    skip_effect_applied: bool = False

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "operation id", required=True, maximum=120))
        if self.type not in OPERATION_TYPES:
            raise ValueError(f"unsupported operation type: {self.type}")
        if not isinstance(self.target, dict):
            raise ValueError("operation target must be an object")
        for key in ("entity_type", "entity_id", "field"):
            if not str(self.target.get(key, "")).strip():
                raise ValueError(f"operation target.{key} is required")
        if self.status not in OPERATION_STATUSES:
            raise ValueError(f"unsupported operation status: {self.status}")
        if not isinstance(self.depends_on, list) or not all(isinstance(item, str) and item.strip() for item in self.depends_on):
            raise ValueError("operation depends_on must be a list of operation ids")
        if self.sync_basis not in {None, "mirror_deadline"}:
            raise ValueError(f"unsupported sync_basis: {self.sync_basis}")
        if self.skip_effect not in {None, "pause_link"}:
            raise ValueError(f"unsupported skip_effect: {self.skip_effect}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Operation":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**_pick(value, known))


@dataclass
class ChangeSet:
    id: str
    version: int
    title: str
    course_id: str
    semester: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    summary: str
    evidence_ids: list[str]
    operations: list[Operation]
    conflicts: list[dict[str, Any]]
    warnings: list[str]
    impact: dict[str, Any]
    approval: dict[str, Any]
    execution: dict[str, Any]
    result: dict[str, Any]
    reversal: dict[str, Any]

    def __post_init__(self) -> None:
        self.id = str(text(self.id, "changeset id", required=True, maximum=120))
        if self.status not in CHANGESET_STATUSES:
            raise ValueError(f"unsupported changeset status: {self.status}")
        if not isinstance(self.operations, list) or not self.operations:
            raise ValueError("changeset must contain at least one operation")
        if len({operation.id for operation in self.operations}) != len(self.operations):
            raise ValueError("changeset contains duplicate operation ids")
        identifiers = {operation.id for operation in self.operations}
        for operation in self.operations:
            unknown = set(operation.depends_on) - identifiers
            if unknown:
                raise ValueError(f"operation depends on unknown operation: {sorted(unknown)[0]}")
        _assert_acyclic(self.operations)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["operations"] = [operation.to_dict() for operation in self.operations]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChangeSet":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        selected = _pick(value, known)
        selected["operations"] = [Operation.from_dict(item) for item in value.get("operations", []) if isinstance(item, dict)]
        return cls(**selected)


def _assert_acyclic(operations: list[Operation]) -> None:
    by_id = {operation.id: operation for operation in operations}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(operation_id: str) -> None:
        if operation_id in visited:
            return
        if operation_id in visiting:
            raise ValueError("operation dependencies contain a cycle")
        visiting.add(operation_id)
        for dependency in by_id[operation_id].depends_on:
            visit(dependency)
        visiting.remove(operation_id)
        visited.add(operation_id)

    for operation in operations:
        visit(operation.id)


def approval_payload(changeset: ChangeSet) -> dict[str, Any]:
    return {
        "id": changeset.id,
        "version": changeset.version,
        "course_id": changeset.course_id,
        "semester": changeset.semester,
        "evidence_ids": changeset.evidence_ids,
        "operations": [
            {
                "id": operation.id,
                "type": operation.type,
                "target": operation.target,
                "before": operation.before,
                "after": operation.after,
                "depends_on": operation.depends_on,
                "required": operation.required,
                "default_selected": operation.default_selected,
                "reversible": operation.reversible,
                "sync_basis": operation.sync_basis,
                "skip_effect": operation.skip_effect,
                "expected_revision": operation.expected_revision,
                "evidence_ids": operation.evidence_ids,
            }
            for operation in changeset.operations
        ],
    }


def approval_hash(changeset: ChangeSet) -> str:
    return sha256_json(approval_payload(changeset))


def operation_by_id(changeset: ChangeSet, operation_id: str) -> Operation:
    for operation in changeset.operations:
        if operation.id == operation_id:
            return operation
    raise KeyError(f"operation not found: {operation_id}")


def operation_counts(changeset: ChangeSet) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in changeset.operations:
        counts[operation.status] = counts.get(operation.status, 0) + 1
    return counts


def derive_changeset_status(changeset: ChangeSet) -> str:
    """Derive a truthful status from operation states.

    Verified/skipped operations are complete. Failed/blocked/conflict operations
    keep the ChangeSet from claiming full success. Reversal status is managed by
    the executor because it has separate semantics.
    """
    if changeset.reversal.get("status") in {"reverted", "partially_reverted", "reversal_conflict"}:
        return str(changeset.reversal["status"])
    statuses = [operation.status for operation in changeset.operations]
    if all(status in {"verified", "skipped", "reversed", "already_reversed"} for status in statuses):
        return "verified" if all(status in {"verified", "skipped"} for status in statuses) else "reverted"
    if any(status in {"failed", "blocked", "conflict", "reversal_conflict"} for status in statuses):
        if any(status == "verified" for status in statuses):
            return "partially_applied"
        return "failed"
    if any(status in {"executing", "approved"} for status in statuses):
        return "executing" if any(status == "executing" for status in statuses) else "approved"
    return "proposed"
