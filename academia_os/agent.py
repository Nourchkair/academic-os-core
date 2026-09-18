from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .acquisition import capability_report
from .activity import ActivityEvent, ActivityLog
from .course_identity import resolve_course_identifier
from .domain import DomainProjection
from .library import list_material
from .processing import ProcessingRecord, ProcessingStore, ProcessingStatus
from .review import ReviewItem, ReviewQueue
from .workflow import is_review_rejection_decision
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
    return resolve_course_identifier(courses, requested)


_SENSITIVE_KEYS = frozenset({
    "password",
    "passwd",
    "access_token",
    "refresh_token",
    "session_token",
    "api_key",
    "apikey",
    "client_secret",
    "cookie",
    "cookies",
    "mfa_code",
    "authorization",
})


def _normalized_key(key: str | None) -> str:
    return str(key or "").strip().casefold().replace("-", "_")


def _sanitize_value(value: Any, root: Path, *, key: str | None = None, depth: int = 0) -> Any:
    if _normalized_key(key) in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_value(item, root, key=str(item_key), depth=depth + 1)
            for item_key, item in list(value.items())[:32]
        }
    if isinstance(value, list):
        return [_sanitize_value(item, root, depth=depth + 1) for item in value[:32]]
    if isinstance(value, str):
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
    result = {
        key: item.get(key)
        for key in (
            "id",
            "name",
            "relative_path",
            "semester",
            "course_id",
            "category",
            "provenance",
            "source_type",
        )
    }
    for key in ("artifact_id", "artifact_kind", "created_by", "authoritative", "source_refs"):
        if item.get(key) is not None:
            result[key] = item[key]
    return result


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


def _recommended_action(action_id: str, label: str, reason: str) -> dict[str, Any]:
    return {"id": action_id, "label": label, "reason": reason, "executable": False}


def _review_choice_candidates(details: dict[str, Any], item: ReviewItem, root: Path) -> list[dict[str, Any]]:
    choices_value = details.get("choices")
    candidates: list[dict[str, Any]] = []
    if isinstance(choices_value, list):
        for choice in choices_value:
            if isinstance(choice, dict) and str(choice.get("id", "")).strip() and str(choice.get("label", "")).strip():
                candidates.append({
                    "id": str(choice["id"]),
                    "label": _sanitize_value(str(choice["label"]), root),
                    "effect": _sanitize_value(str(choice.get("effect", "")), root),
                })
    if candidates:
        return candidates
    current_value = details.get("current_value", details.get("current"))
    proposed_value = details.get("proposed_value", details.get("new"))
    if current_value is not None:
        candidates.append({
            "id": "keep_current",
            "label": f"Keep {_sanitize_value(current_value, root)}",
            "effect": "Reject the linked proposal; keep the currently saved value.",
        })
    if proposed_value is not None:
        candidates.append({
            "id": "use_new",
            "label": f"Use {_sanitize_value(proposed_value, root)}",
            "effect": "Approve the linked proposal; execute it separately, then verify the result.",
        })
    if not candidates and item.action_proposal_id:
        candidates.extend([
            {"id": "approve", "label": "Approve the linked action", "effect": "Approve the proposal; execute it separately, then verify the result."},
            {"id": "reject", "label": "Reject the linked action", "effect": "Reject the proposal without executing it."},
        ])
    return candidates


def _attention_review(item: ReviewItem, root: Path, *, course_label: str | None = None) -> dict[str, Any]:
    details = dict(item.details)
    evidence_value = details.get("evidence", details.get("evidence_refs", []))
    if isinstance(evidence_value, list):
        evidence = [_sanitize_value(value if isinstance(value, dict) else {"reference": str(value)}, root) for value in evidence_value]
    elif evidence_value:
        evidence = [_sanitize_value({"reference": str(evidence_value)}, root)]
    else:
        evidence = []

    candidates = _review_choice_candidates(details, item, root)
    proposal_details = details.get("proposal_details")
    proposal_action_type = proposal_details.get("action_type") if isinstance(proposal_details, dict) else None
    action_type = str(details.get("action_type") or proposal_action_type or "")
    execution_supported = action_type == "domain_change"
    choices: list[dict[str, Any]] = []
    recommended: list[dict[str, Any]] = []
    if item.action_proposal_id:
        for candidate in candidates:
            decision = str(candidate["id"])
            requires_execution = not is_review_rejection_decision(decision)
            if requires_execution and not execution_supported:
                recommended.append(_recommended_action(
                    decision,
                    str(candidate["label"]),
                    "The linked action has no supported Academia execution step yet; do not treat this as performed.",
                ))
                continue
            action: dict[str, Any] = {
                "type": "review_decision",
                "review_id": item.id,
                "decision": decision,
                "requires_execution": requires_execution,
            }
            if requires_execution:
                action["execution"] = {
                    "type": "review_execute",
                    "review_id": item.id,
                    "proposal_id": item.action_proposal_id,
                }
            choices.append({
                "id": decision,
                "label": candidate["label"],
                "effect": candidate["effect"],
                "executable": True,
                "action": action,
            })
    else:
        for candidate in candidates:
            recommended.append(_recommended_action(
                str(candidate["id"]),
                str(candidate["label"]),
                str(candidate.get("effect") or "No linked Academia action executor is available for this guidance."),
            ))
        if not recommended and item.kind == "source_verification":
            recommended.append(_recommended_action(
                "verify_source",
                "Verify the source before treating this fact as confirmed.",
                "Source verification is guidance only; no supported Review action executor is linked.",
            ))
        elif not recommended and item.kind == "import_classification":
            recommended.append(_recommended_action(
                "review_import_classification",
                "Choose the import destination through an approved import workflow.",
                "This Review item has no linked action executor for moving or classifying the file.",
            ))
        elif not recommended:
            recommended.append(_recommended_action(
                "review_with_student",
                "Review this item with the student.",
                "No linked Academia action executor is available for this Review item.",
            ))

    why_value = details.get("why_this_needs_human_input") or details.get("reason")
    if why_value is None:
        evidence_reason = details.get("evidence")
        why_value = evidence_reason if isinstance(evidence_reason, str) else "Academia OS cannot safely choose between these alternatives without the student's judgment."
    current_value = details.get("current_value", details.get("current"))
    proposed_value = details.get("proposed_value", details.get("new"))
    return {
        "id": item.id,
        "kind": item.kind,
        "course": _sanitize_value(course_label if course_label is not None else item.course, root),
        "question": _sanitize_value(str(details.get("question") or item.title), root),
        "why_this_needs_human_input": _sanitize_value(why_value, root),
        "current_value": _sanitize_value(current_value, root),
        "proposed_value": _sanitize_value(proposed_value, root),
        "evidence": evidence,
        "choices": choices,
        "recommended_next_actions": recommended,
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


def _normalized_review_course(item: ReviewItem, courses: list[dict[str, Any]]) -> str | None:
    if item.course is None:
        return None
    try:
        return str(resolve_course_identifier(courses, str(item.course))["id"])
    except (KeyError, ValueError):
        return str(item.course)


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
    available_courses = [dict(course) for course in snapshot.get("courses", [])]
    stored_reviews = ReviewQueue(root / ".academia" / "review.json").list()
    normalized_reviews = [(item, _normalized_review_course(item, available_courses)) for item in stored_reviews]
    if course_id:
        normalized_reviews = [(item, normalized) for item, normalized in normalized_reviews if normalized in {None, course_id}]
    elif course_ids is not None:
        normalized_reviews = [(item, normalized) for item, normalized in normalized_reviews if normalized is None or normalized in course_ids]
    processing = ProcessingStore(root / ".academia" / "processing.json")
    records = processing.list()
    if semester:
        records = [record for record in records if (_safe_relative(record.source_path, root) or "").split("/", 1)[0] == semester]
    failed_processing, pending_processing = _processing_attention(records, root, detail)
    review_items = [
        _attention_review(item, root, course_label=normalized)
        for item, normalized in normalized_reviews[:_limit(detail, "attention")]
    ]
    conflicts = [item for item in review_items if "conflict" in item["kind"].casefold() or "conflict" in item["question"].casefold()]
    uncertain = [item for item in review_items if "uncertain" in item["kind"].casefold() or "classification" in item["kind"].casefold() or item["kind"] == "source_verification"]
    projection = DomainProjection(root / ".academia" / "domain.json")
    scoped_course_ids = {course_id} if course_id else (course_ids if course_ids is not None else {str(course.get("id")) for course in available_courses})
    unverified = []
    for entity in projection.list():
        if entity.get("course_id") not in scoped_course_ids:
            continue
        evidence_value = entity.get("evidence")
        evidence = evidence_value if isinstance(evidence_value, dict) else {}
        if evidence.get("confidence") not in {None, "current-confirmed"}:
            item = _compact_entity(entity, root)
            if item.get("evidence") is not None:
                unverified.append(item)

    processing_items = [
        {
            "id": item["id"],
            "kind": "processing_failure",
            "course": None,
            "question": f"Processing failed for {item.get('source') or 'an academic file'}",
            "why_this_needs_human_input": item.get("failure_reason") or "Processing requires an agent retry or a different authorized handling path.",
            "current_value": item.get("status"),
            "proposed_value": None,
            "evidence": [{"reference": item.get("source")}],
            "choices": [],
            "recommended_next_actions": [_recommended_action(
                "retry_processing",
                "Retry processing",
                "No supported processing retry command is exposed by this contract yet.",
            )],
            "action_proposal_id": None,
            "status": item.get("status"),
            "priority": "normal",
            "created_at": item.get("updated_at"),
            "updated_at": item.get("updated_at"),
        }
        for item in failed_processing
    ]
    unverified_items = [
        {
            "id": item.get("id"),
            "kind": "unverified_fact",
            "course": item.get("course_id"),
            "question": f"Verify the academic fact: {item.get('title') or item.get('id')}",
            "why_this_needs_human_input": "The current evidence is not marked current-confirmed.",
            "current_value": item,
            "proposed_value": None,
            "evidence": [item.get("evidence")],
            "choices": [],
            "recommended_next_actions": [_recommended_action(
                "verify_source",
                "Verify source before treating as confirmed",
                "Verification is guidance only; no supported Review action executor is linked.",
            )],
            "action_proposal_id": None,
            "status": "attention",
            "priority": "normal",
            "created_at": None,
            "updated_at": None,
        }
        for item in unverified
    ]
    attention_items = [*review_items, *processing_items, *unverified_items][:_limit(detail, "attention")]
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
    if scope == "course":
        materials = [item for item in materials if item.get("course_id") in ids]
    else:
        materials = [item for item in materials if item.get("course_id") in ids or (item.get("category") == "imports" and item.get("course_id") is None)]
    readings = [_compact_library_item(item) for item in materials if item.get("category") == "readings"]
    source_items = materials
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
    canonical_course_id = None
    if course_id:
        canonical_course_id = str(resolve_course_identifier(snapshot.get("courses", []), course_id)["id"])
    course_ids = {str(course.get("id")) for course in snapshot.get("courses", [])}
    return build_attention(config, snapshot, detail=detail, course_id=canonical_course_id, course_ids=None if canonical_course_id else course_ids, semester=str(snapshot.get("semester") or ""))


def build_agent_capabilities() -> dict[str, Any]:
    return _capability_view()
