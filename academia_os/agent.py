from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .acquisition import capability_report
from .activity import ActivityEvent, ActivityLog
from .domain import DomainProjection
from .library import list_material
from .processing import ProcessingRecord, ProcessingStore, ProcessingStatus
from .review import ReviewItem, ReviewQueue
from .workspace import build_workspace_snapshot

AGENT_CONTEXT_SCHEMA_VERSION = 1
DETAIL_LIMITS: dict[str, dict[str, int]] = {
    "compact": {"courses": 12, "tasks": 8, "deadlines": 6, "assignments": 6, "readings": 8, "sources": 12, "attention": 20, "activity": 6},
    "standard": {"courses": 40, "tasks": 25, "deadlines": 15, "assignments": 15, "readings": 20, "sources": 30, "attention": 50, "activity": 15},
    "deep": {"courses": 100, "tasks": 100, "deadlines": 50, "assignments": 50, "readings": 80, "sources": 100, "attention": 100, "activity": 50},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generated_at() -> str:
    return _now().isoformat()


def _limit(detail: str, key: str) -> int:
    try:
        return DETAIL_LIMITS[detail][key]
    except KeyError as exc:
        raise ValueError(f"detail must be one of: {', '.join(DETAIL_LIMITS)}") from exc


def _safe_relative(path: str | Path, root: Path) -> str | None:
    try:
        raw = Path(path).expanduser()
        candidate = raw if raw.is_absolute() else root / raw
        candidate = candidate.resolve()
        relative = candidate.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if ".academia" in relative.parts:
        return None
    return relative.as_posix()


def _course_match(courses: list[dict[str, Any]], requested: str | None) -> dict[str, Any] | None:
    if not requested:
        return None
    folded = requested.casefold()
    matches = [course for course in courses if folded in {str(course.get("id", "")).casefold(), str(course.get("code", "")).casefold(), str(course.get("name", "")).casefold()}]
    if not matches:
        raise KeyError(f"course not found: {requested}")
    if len(matches) > 1:
        raise ValueError(f"course identifier is ambiguous: {requested}")
    return matches[0]


def _sanitize_value(value: Any, root: Path, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item, root, depth=depth + 1) for key, item in list(value.items())[:32]}
    if isinstance(value, list):
        return [_sanitize_value(item, root, depth=depth + 1) for item in value[:32]]
    if isinstance(value, str):
        lowered = value.casefold()
        if any(token in lowered for token in ("password", "passwd", "token", "secret", "api_key", "apikey", "cookie", "mfa")):
            return "[REDACTED]"
        if value.startswith("/") or value.startswith("~"):
            relative = _safe_relative(value, root)
            return relative or "[OUTSIDE_WORKSPACE]"
        if ".academia" in Path(value).parts:
            return "[OPERATIONAL_STATE]"
        return value[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _compact_course(course: dict[str, Any], root: Path) -> dict[str, Any]:
    result = {key: course.get(key) for key in ("id", "code", "name", "inbox_count", "material_count", "review_required") if key in course}
    for key in ("path", "status_file"):
        if course.get(key):
            relative = _safe_relative(str(course[key]), root)
            if relative is not None:
                result[key] = relative
    return result


def _compact_library_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in ("id", "name", "relative_path", "semester", "course_id", "category", "provenance", "artifact_id", "artifact_kind", "created_by", "authoritative", "source_refs") if item.get(key) is not None}


def _scope_courses(courses: list[dict[str, Any]], scope: str, course: dict[str, Any] | None) -> list[dict[str, Any]]:
    if scope == "course":
        if course is None:
            raise ValueError("course scope requires --course")
        return [course]
    return courses


def _course_ids(courses: list[dict[str, Any]]) -> set[str]:
    return {str(course.get("id", "")) for course in courses}


def _entity_evidence(entity: dict[str, Any], root: Path) -> dict[str, Any] | None:
    evidence = entity.get("evidence")
    if not isinstance(evidence, dict):
        return None
    source_path = _safe_relative(str(evidence.get("source_path", "")), root)
    if source_path is None:
        return None
    return {
        "entity_type": entity.get("entity_type"),
        "entity_id": entity.get("id"),
        "source": evidence.get("source"),
        "path": source_path,
        "location": evidence.get("source_location"),
        "provenance": evidence.get("provenance"),
        "confidence": evidence.get("confidence"),
        "authority": evidence.get("authority"),
        "verification_result": evidence.get("verification_result"),
    }


def _compact_task(task: dict[str, Any], root: Path) -> dict[str, Any]:
    result = {key: task.get(key) for key in ("title", "completed", "course", "confidence", "kind", "due_date") if key in task}
    raw_id = str(task.get("id", ""))
    if raw_id.startswith("/") and ":" in raw_id:
        source_path, line = raw_id.rsplit(":", 1)
        relative = _safe_relative(source_path, root)
        result["id"] = f"{relative}:{line}" if relative is not None else f"task:{line}"
    else:
        result["id"] = raw_id
    source = _safe_relative(str(task.get("source", "")), root)
    if source is not None:
        result["source"] = source
    if task.get("source_location") is not None:
        result["source_location"] = _sanitize_value(task.get("source_location"), root)
    return result


def _compact_entity(entity: dict[str, Any], root: Path, *, include_assignment_fields: bool = False) -> dict[str, Any]:
    result = {key: entity.get(key) for key in ("entity_type", "id", "course_id", "title", "date", "deadline", "time", "type", "status", "week_or_topic") if key in entity}
    if include_assignment_fields:
        result.update({key: entity.get(key) for key in ("weight", "submission_method", "instructions_source", "rubric_source") if key in entity})
    evidence = _entity_evidence(entity, root)
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _attention_review(item: ReviewItem, root: Path) -> dict[str, Any]:
    details = dict(item.details)
    evidence_value = details.get("evidence", details.get("evidence_refs", []))
    if isinstance(evidence_value, list):
        evidence = [_sanitize_value(value if isinstance(value, dict) else {"reference": str(value)}, root) for value in evidence_value]
    elif evidence_value:
        evidence = [_sanitize_value({"reference": str(evidence_value)}, root)]
    else:
        evidence = []
    choices_value = details.get("choices")
    choices: list[dict[str, Any]] = []
    if isinstance(choices_value, list):
        for choice in choices_value:
            if isinstance(choice, dict) and str(choice.get("id", "")).strip() and str(choice.get("label", "")).strip():
                choices.append({"id": str(choice["id"]), "label": _sanitize_value(str(choice["label"]), root), "effect": _sanitize_value(str(choice.get("effect", "")), root)})
    if not choices:
        current_value = details.get("current_value", details.get("current"))
        proposed_value = details.get("proposed_value", details.get("new"))
        if current_value is not None:
            choices.append({"id": "keep_current", "label": f"Keep {_sanitize_value(current_value, root)}", "effect": "No proposed value will be applied."})
        if proposed_value is not None:
            choices.append({"id": "use_new", "label": f"Use {_sanitize_value(proposed_value, root)}", "effect": "Apply only through the existing approved action workflow."})
        if item.kind == "import_classification":
            choices.append({"id": "keep_general_intake", "label": "Keep in general intake", "effect": "Preserve the file without classifying or moving it."})
    current_value = details.get("current_value", details.get("current"))
    proposed_value = details.get("proposed_value", details.get("new"))
    return {
        "id": item.id,
        "kind": item.kind,
        "course": _sanitize_value(item.course, root),
        "question": _sanitize_value(str(details.get("question") or item.title), root),
        "why_this_needs_human_input": _sanitize_value(str(details.get("why_this_needs_human_input") or details.get("reason") or details.get("evidence") or "Academia OS cannot safely choose between these alternatives without the student's judgment."), root),
        "current_value": _sanitize_value(current_value, root),
        "proposed_value": _sanitize_value(proposed_value, root),
        "evidence": evidence,
        "choices": choices,
        "action_proposal_id": item.action_proposal_id,
        "status": item.status.value,
        "priority": item.priority,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _processing_attention(records: list[ProcessingRecord], root: Path, detail: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for record in records:
        source = _safe_relative(record.source_path, root)
        item = {
            "id": record.id,
            "status": record.status.value,
            "source": source,
            "retry_count": record.retry_count,
            "failure_reason": _sanitize_value(record.failure_reason, root),
            "updated_at": record.updated_at,
        }
        if record.status is ProcessingStatus.FAILED:
            failed.append(item)
        elif record.status in {ProcessingStatus.PENDING, ProcessingStatus.PROCESSING, ProcessingStatus.VERIFIED}:
            pending.append(item)
    return failed[:_limit(detail, "attention")], pending[:_limit(detail, "attention")]


def _activity_refs(events: list[ActivityEvent], root: Path, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events[:limit]:
        item = {
            "id": event.id,
            "event_type": event.event_type,
            "title": _sanitize_value(event.title, root),
            "course": _sanitize_value(event.course, root),
            "details": _sanitize_value({key: value for key, value in event.details.items() if key not in {"content", "body"}}, root),
            "confidence": event.confidence,
            "actor": _sanitize_value(event.actor, root),
            "created_at": event.created_at,
        }
        if event.source:
            source = _safe_relative(event.source, root)
            if source is not None:
                item["source"] = source
        result.append(item)
    return result


def _date_value(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _filter_today(tasks: list[dict[str, Any]], deadlines: list[dict[str, Any]], timezone_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        today = _now().astimezone(ZoneInfo(timezone_name)).date()
    except Exception:
        today = _now().date()
    end = today + timedelta(days=7)
    def due_soon(task: dict[str, Any]) -> bool:
        if task.get("completed"):
            return False
        parsed = _date_value(task.get("due_date"))
        return parsed is None or parsed <= end

    def deadline_soon(item: dict[str, Any]) -> bool:
        parsed = _date_value(item.get("date"))
        return parsed is None or parsed <= end

    task_result = [task for task in tasks if due_soon(task)]
    deadline_result = [item for item in deadlines if deadline_soon(item)]
    return task_result, deadline_result


def build_attention(
    config: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    detail: str = "standard",
    course_id: str | None = None,
    course_ids: set[str] | None = None,
    semester: str | None = None,
) -> dict[str, Any]:
    _limit(detail, "attention")
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    reviews = ReviewQueue(root / ".academia" / "review.json").list()
    if course_id:
        reviews = [item for item in reviews if item.course in {None, course_id}]
    elif course_ids is not None:
        reviews = [item for item in reviews if item.course is None or item.course in course_ids]
    processing = ProcessingStore(root / ".academia" / "processing.json")
    records = processing.list()
    if semester:
        records = [record for record in records if (_safe_relative(record.source_path, root) or "").split("/", 1)[0] == semester]
    failed_processing, pending_processing = _processing_attention(records, root, detail)
    review_items = [_attention_review(item, root) for item in reviews[:_limit(detail, "attention")]]
    conflicts = [item for item in review_items if "conflict" in item["kind"].casefold() or "conflict" in item["question"].casefold()]
    uncertain = [item for item in review_items if "uncertain" in item["kind"].casefold() or "classification" in item["kind"].casefold() or item["kind"] == "source_verification"]
    projection = DomainProjection(root / ".academia" / "domain.json")
    course_ids = {course_id} if course_id else {str(course.get("id")) for course in snapshot.get("courses", [])}
    unverified = []
    for entity in projection.list():
        if entity.get("course_id") not in course_ids:
            continue
        evidence_value = entity.get("evidence")
        evidence = evidence_value if isinstance(evidence_value, dict) else {}
        if evidence.get("confidence") not in {None, "current-confirmed"}:
            item = _compact_entity(entity, root)
            if item.get("evidence") is not None:
                unverified.append(item)
    attention_items = [*review_items, *[{"id": item["id"], "kind": "processing_failure", "course": None, "question": f"Processing failed for {item.get('source') or 'an academic file'}", "why_this_needs_human_input": item.get("failure_reason") or "Processing requires an agent retry or a different authorized handling path.", "current_value": item.get("status"), "proposed_value": None, "evidence": [{"reference": item.get("source")}], "choices": [{"id": "retry", "label": "Retry processing", "effect": "Return the item to the retryable processing state."}], "action_proposal_id": None, "status": item.get("status"), "priority": "normal", "created_at": item.get("updated_at"), "updated_at": item.get("updated_at")} for item in failed_processing]]
    attention_items.extend({"id": item.get("id"), "kind": "unverified_fact", "course": item.get("course_id"), "question": f"Verify the academic fact: {item.get('title') or item.get('id')}", "why_this_needs_human_input": "The current evidence is not marked current-confirmed.", "current_value": item, "proposed_value": None, "evidence": [item.get("evidence")], "choices": [{"id": "verify_source", "label": "Verify source before treating as confirmed", "effect": "Keep the fact non-authoritative until verification."}], "action_proposal_id": None, "status": "attention", "priority": "normal", "created_at": None, "updated_at": None} for item in unverified)
    attention_items = attention_items[:_limit(detail, "attention")]
    return {
        "schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "count": len(attention_items),
        "items": attention_items,
        "needs_human_input": review_items,
        "conflicts": conflicts[:_limit(detail, "attention")],
        "failed_processing": failed_processing,
        "pending_processing": pending_processing,
        "uncertain_classification": uncertain[:_limit(detail, "attention")],
        "important_unverified_facts": unverified[:_limit(detail, "attention")],
    }


def _capability_view() -> dict[str, Any]:
    report = capability_report()
    return {
        "schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "allowed_directly": list(report["allowed_directly"]),
        "approval_required": list(report["approval_required"]),
        "prohibited": list(report["prohibited"]),
        "implementation": {key: value for key, value in report.items() if key not in {"allowed_directly", "approval_required", "prohibited"}},
    }


def build_agent_context(config: dict[str, Any], snapshot: dict[str, Any], *, scope: str = "workspace", detail: str = "standard", course_id: str | None = None, semester: str | None = None) -> dict[str, Any]:
    if scope not in {"workspace", "semester", "course", "today"}:
        raise ValueError("scope must be one of: workspace, semester, course, today")
    for key in ("courses", "tasks", "deadlines", "assignments", "readings", "sources", "attention", "activity"):
        _limit(detail, key)
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    current_semester = str(snapshot["semester"])
    course = _course_match(snapshot.get("courses", []), course_id)
    scoped_courses = _scope_courses(snapshot.get("courses", []), scope, course)
    ids = _course_ids(scoped_courses)
    projection = DomainProjection(root / ".academia" / "domain.json")
    entities = [entity for entity in projection.list() if str(entity.get("course_id", "")) in ids]
    tasks = [_compact_task(task, root) for task in snapshot.get("tasks", []) if str(task.get("course", "")) in ids]
    open_tasks = [task for task in tasks if not task.get("completed")]
    deadlines = [_compact_entity(entity, root) for entity in entities if entity.get("entity_type") == "deadline" and entity.get("evidence", {}).get("confidence") == "current-confirmed"]
    assignments = [_compact_entity(entity, root, include_assignment_fields=True) for entity in entities if entity.get("entity_type") == "assignment"]
    materials = list_material(root, current_semester)
    materials = [item for item in materials if item.get("course_id") in ids]
    readings = [_compact_library_item(item) for item in materials if item.get("category") == "readings"]
    source_items = [item for item in materials if item.get("category") in {"readings", "generated"}]
    if scope == "today":
        open_tasks, deadlines = _filter_today(open_tasks, deadlines, str(config["academic"]["timezone"]))
    open_tasks = open_tasks[:_limit(detail, "tasks")]
    deadlines = sorted(deadlines, key=lambda item: (str(item.get("date") or "9999-99-99"), str(item.get("title", ""))))[:_limit(detail, "deadlines")]
    assignments = assignments[:_limit(detail, "assignments")]
    readings = readings[:_limit(detail, "readings")]
    library_items = [_compact_library_item(item) for item in source_items[:_limit(detail, "sources")]]
    evidence_refs = [_entity_evidence(entity, root) for entity in entities]
    evidence_refs = [item for item in evidence_refs if item is not None][: _limit(detail, "sources")]
    attention = build_attention(config, snapshot, detail=detail, course_id=course.get("id") if course else None, course_ids=ids if course is None else None, semester=current_semester)
    events = ActivityLog(root / ".academia" / "activity.jsonl").list(limit=_limit(detail, "activity"))
    if course is not None:
        events = [event for event in events if event.course in {None, course.get("id")}]
    activity = _activity_refs(events, root, _limit(detail, "activity"))
    compact_courses = [_compact_course(item, root) for item in scoped_courses]
    scoped_snapshot = {
        "course_count": len(scoped_courses),
        "material_count": len(materials),
        "open_task_count": len(open_tasks),
        "next_deadline_count": len(deadlines),
    }
    context: dict[str, Any] = {
        "schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "detail": detail,
        "scope": {"kind": scope, "semester": current_semester, **({"course_id": course["id"]} if course else {})},
        "workspace": {
            "workspace_reference": "configured_workspace",
            "timezone": config["academic"]["timezone"],
            "available_semesters": snapshot.get("available_semesters", []),
            **scoped_snapshot,
        },
        "semester": {"id": current_semester, "name": current_semester, "selected": True},
        "current_state": {
            "courses": compact_courses[:_limit(detail, "courses")],
            "open_tasks": open_tasks,
            "next_deadlines": deadlines,
            "current_assignments": assignments,
            "relevant_readings": readings,
        },
        "attention": attention,
        "recent_changes": activity,
        "sources": {
            "library_items": library_items,
            "evidence_references": evidence_refs,
        },
        "capabilities": _capability_view(),
        "safe_write_locations": {
            "generated_artifacts": [
                {"course_id": item["id"], "relative_directory": f"{current_semester}/{item['id']}/06_KNOWLEDGE/AI_GENERATED", "create_only": True}
                for item in scoped_courses[:_limit(detail, "courses")]
            ],
            "controlled_by": "academia",
            "original_files_writable_through_artifact_api": False,
        },
    }
    if course is not None:
        context["course"] = _compact_course(course, root)
    return context


def build_agent_changes(config: dict[str, Any], *, since: str | None = None, limit: int = 100) -> dict[str, Any]:
    if not isinstance(limit, int) or limit < 1 or limit > 500:
        raise ValueError("changes limit must be between 1 and 500")
    root = Path(config["academic"]["root_directory"]).expanduser().resolve()
    events, next_cursor = ActivityLog(root / ".academia" / "activity.jsonl").changes_since(since, limit=limit)
    return {
        "schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "generated_at": _generated_at(),
        "since": since,
        "count": len(events),
        "changes": _activity_refs(events, root, limit),
        "next_cursor": next_cursor,
        "cursor_kind": "activity_id",
    }


def build_agent_attention(config: dict[str, Any], snapshot: dict[str, Any], *, detail: str = "standard", course_id: str | None = None) -> dict[str, Any]:
    course_ids = {str(course.get("id")) for course in snapshot.get("courses", [])}
    return build_attention(config, snapshot, detail=detail, course_id=course_id, course_ids=None if course_id else course_ids, semester=str(snapshot.get("semester") or ""))


def build_agent_capabilities() -> dict[str, Any]:
    return _capability_view()
