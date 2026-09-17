from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .provenance import ProvenanceLabel
from .state import JsonStateStore


ENTITY_TYPES = ("academic_source", "deadline", "assignment", "reading", "announcement", "course_meeting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Evidence:
    source: str
    source_path: str
    source_location: str | None = None
    provenance: str = ProvenanceLabel.ORIGINAL.value
    confidence: str = "unverified"
    authority: str = "unknown"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_verified_at: str | None = None
    source_hash: str | None = None
    reference: dict[str, Any] | None = None
    excerpt: str | None = None


@dataclass(frozen=True)
class AcademicSource:
    entity_type: ClassVar[str] = "academic_source"
    id: str
    course_id: str
    title: str
    kind: str
    evidence: Evidence
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Deadline:
    entity_type: ClassVar[str] = "deadline"
    id: str
    course_id: str
    title: str
    date: str | None
    time: str | None
    type: str
    evidence: Evidence


@dataclass(frozen=True)
class Assignment:
    entity_type: ClassVar[str] = "assignment"
    id: str
    course_id: str
    title: str
    deadline: str | None
    weight: str | None
    instructions_source: str | None
    rubric_source: str | None
    submission_method: str | None
    status: str | None
    evidence: Evidence


@dataclass(frozen=True)
class Reading:
    entity_type: ClassVar[str] = "reading"
    id: str
    course_id: str
    title: str
    week_or_topic: str | None
    author: str | None
    edition: str | None
    chapter: str | None
    pages: str | None
    doi: str | None
    isbn: str | None
    required: bool | None
    verification_result: str | None
    evidence: Evidence


@dataclass(frozen=True)
class Announcement:
    entity_type: ClassVar[str] = "announcement"
    id: str
    course_id: str
    title: str
    published_at: str | None
    body_reference: str | None
    evidence: Evidence


@dataclass(frozen=True)
class CourseMeeting:
    entity_type: ClassVar[str] = "course_meeting"
    id: str
    course_id: str
    title: str
    starts_at: str | None
    ends_at: str | None
    location: str | None
    meeting_type: str | None
    evidence: Evidence


Entity = AcademicSource | Deadline | Assignment | Reading | Announcement | CourseMeeting


class DomainProjection:
    """Persist derived academic entities without replacing source files.

    The projection is intentionally inert: extraction code must construct an
    entity with evidence before it can be stored. Missing academic values stay
    null rather than being inferred here.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.store = JsonStateStore(self.path)

    def _state(self) -> dict[str, Any]:
        value = self.store.read({"schema_version": 1, "entities": {}})
        if not isinstance(value, dict):
            return {"schema_version": 1, "entities": {}}
        entities = value.get("entities")
        if not isinstance(entities, dict):
            value["entities"] = {}
        return value

    @staticmethod
    def _validate(entity: Entity) -> tuple[str, dict[str, Any]]:
        entity_type = getattr(entity, "entity_type", None)
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"unsupported domain entity: {entity_type}")
        value = asdict(entity)
        if not str(value.get("id", "")).strip():
            raise ValueError("domain entity id is required")
        if not str(value.get("course_id", "")).strip():
            raise ValueError("domain entity course_id is required")
        evidence = value.get("evidence")
        if not isinstance(evidence, dict) or not str(evidence.get("source_path", "")).strip():
            raise ValueError("domain entity evidence.source_path is required")
        if ".academia" in Path(str(evidence["source_path"])).expanduser().parts:
            raise ValueError("domain entity evidence cannot point to .academia operational state")
        if evidence.get("provenance") not in {label.value for label in ProvenanceLabel}:
            raise ValueError("domain entity evidence.provenance is invalid")
        if not str(evidence.get("confidence", "")).strip():
            raise ValueError("domain entity evidence.confidence is required")
        if not str(evidence.get("authority", "")).strip():
            raise ValueError("domain entity evidence.authority is required")
        return entity_type, value

    def upsert(self, entity: Entity) -> dict[str, Any]:
        entity_type, value = self._validate(entity)
        value["entity_type"] = entity_type

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": 1, "entities": {}}
            entities = state.setdefault("entities", {})
            values = [item for item in entities.get(entity_type, []) if isinstance(item, dict) and item.get("id") != value["id"]]
            values.append(value)
            entities[entity_type] = sorted(values, key=lambda item: str(item.get("id", "")))
            state["schema_version"] = 1
            return state

        self.store.update({"schema_version": 1, "entities": {}}, transition)
        return value

    def list(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        state = self._state()
        entities = state.get("entities", {})
        if entity_type is not None and entity_type not in ENTITY_TYPES:
            raise ValueError(f"unsupported domain entity: {entity_type}")
        if entity_type is not None:
            return list(entities.get(entity_type, []))
        result: list[dict[str, Any]] = []
        for kind in ENTITY_TYPES:
            result.extend(entities.get(kind, []))
        return result

    def counts(self) -> dict[str, int]:
        return {kind: len(self.list(kind)) for kind in ENTITY_TYPES}

    def get(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        for entity in self.list(entity_type):
            if entity.get("id") == entity_id:
                return dict(entity)
        raise KeyError(f"domain entity not found: {entity_type}:{entity_id}")

    def update_field(
        self,
        entity_type: str,
        entity_id: str,
        field_name: str,
        value: Any,
        *,
        expected_before: Any = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"unsupported domain entity: {entity_type}")
        selected: list[dict[str, Any]] = []

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": 1, "entities": {}}
            entities = state.setdefault("entities", {})
            values = entities.setdefault(entity_type, [])
            for index, current in enumerate(values):
                if not isinstance(current, dict) or current.get("id") != entity_id:
                    continue
                if expected_before is not None and current.get(field_name) != expected_before:
                    raise ValueError(f"domain entity changed before update: {entity_type}:{entity_id}.{field_name}")
                updated = dict(current)
                updated[field_name] = value
                if evidence is not None:
                    updated["evidence"] = dict(evidence)
                values[index] = updated
                selected.append(updated)
                return state
            raise KeyError(f"domain entity not found: {entity_type}:{entity_id}")

        self.store.update({"schema_version": 1, "entities": {}}, transition)
        return selected[0]

    def replace_raw(self, entity_type: str, entity_id: str, replacement: dict[str, Any]) -> dict[str, Any]:
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"unsupported domain entity: {entity_type}")

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": 1, "entities": {}}
            values = state.setdefault("entities", {}).setdefault(entity_type, [])
            for index, current in enumerate(values):
                if isinstance(current, dict) and current.get("id") == entity_id:
                    values[index] = dict(replacement)
                    return state
            raise KeyError(f"domain entity not found: {entity_type}:{entity_id}")

        self.store.update({"schema_version": 1, "entities": {}}, transition)
        return dict(replacement)
