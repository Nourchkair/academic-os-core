"""Policy-backed write operations for the assistant.

The model may propose an action; only the existing Review/Action workflow may
approve and execute it.  This first slice covers local file imports.  Every
proposal records the exact source, destination, hash, and effects, and execution
revalidates the source before copying.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from ...acquisition import import_file, validate_import_destination, validate_import_source
from ...actions import ActionProposal, ActionStore, ActionType
from ...activity import ActivityLog
from ...domain import DomainProjection, Evidence
from ...processing import ProcessingStore
from ...review import ReviewItem, ReviewQueue, ReviewStatus
from ...source_identity import SourceIdentityError, fingerprint, safe_workspace_path
from ...study import StudyService
from ...tasks import TaskStateError, TaskStore
from ...workflow import ApprovalWorkflow
from ..contracts import AssistantError, Disclosure, PermissionClass, SideEffect, ToolDescriptor, ToolResult
from .read import ReadContext


IMPORT_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="import.propose",
    version=1,
    description="Propose copying one explicit local file into a recognized course or semester inbox. Creates a Review/Action proposal; it never copies or executes by itself.",
    input_schema={
        "type": "object",
        "properties": {
            "source_path": {"type": "string", "description": "Exact local file path"},
            "target_id": {"type": "string", "description": "Exact inbox id from import targets"},
            "source_label": {"type": "string", "description": "Optional provenance label"},
        },
        "required": ["source_path", "target_id"],
        "additionalProperties": False,
    },
    permission=PermissionClass.WRITE_LOCAL,
    side_effect=SideEffect.CREATE,
    disclosure=Disclosure.LOCAL_ONLY,
    requires_approval=True,
    idempotent=False,
    previewable=True,
    verifiable=True,
)

STUDY_CREATE_DESCRIPTOR = ToolDescriptor(
    name="study.create",
    version=1,
    description="Create one cited, non-authoritative Study set from selected course sources. Create-only; existing sets and attempts remain untouched.",
    input_schema={
        "type": "object",
        "properties": {
            "course": {"type": "string", "description": "Exact course ID, code, or name"},
            "payload": {"type": "object", "description": "Validated Study payload with citation IDs from the retrieved context"},
            "source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 300},
            "query": {"type": "string", "maxLength": 2000},
            "pages": {"type": "string", "maxLength": 40},
            "limit": {"type": "integer", "minimum": 1, "maximum": 128},
            "deep": {"type": "boolean"},
        },
        "required": ["course", "payload"],
        "additionalProperties": False,
    },
    permission=PermissionClass.WRITE_LOCAL,
    side_effect=SideEffect.CREATE,
    disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE,
    requires_approval=False,
    idempotent=False,
    previewable=True,
    verifiable=True,
)

DOMAIN_CHANGE_DESCRIPTOR = ToolDescriptor(
    name="domain.propose",
    version=1,
    description="Propose one evidence-backed change to a derived academic record. Creates a Review/Action proposal and never changes the projection by itself.",
    input_schema={
        "type": "object",
        "properties": {
            "course": {"type": "string"},
            "entity_type": {"type": "string"},
            "entity_id": {"type": "string"},
            "field": {"type": "string"},
            "after": {"type": "string"},
            "evidence_source": {"type": "string"},
            "evidence_path": {"type": "string"},
            "source_location": {"type": "string"},
            "confidence": {"type": "string", "enum": ["current-confirmed", "likely", "unverified", "historical"]},
            "authority": {"type": "string"},
        },
        "required": ["course", "entity_type", "entity_id", "field", "after", "evidence_source", "evidence_path"],
        "additionalProperties": False,
    },
    permission=PermissionClass.WRITE_LOCAL,
    side_effect=SideEffect.UPDATE,
    disclosure=Disclosure.LOCAL_ONLY,
    requires_approval=True,
    idempotent=False,
    previewable=True,
    verifiable=True,
)

TASK_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="task.propose",
    version=1,
    description="Propose creating or updating one personal task in SEMESTER_TASKS.md. Creates a Review/Action proposal; it never writes the task file and cannot mark work complete.",
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update"]},
            "task_id": {"type": "string", "description": "Exact task id for an update"},
            "title": {"type": "string"},
            "course": {"type": "string", "description": "Exact course ID, code, or name"},
            "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD, or null to clear"},
            "due_time": {"type": ["string", "null"], "description": "HH:MM, or null to clear"},
            "evidence_source": {"type": "string", "description": "Human-readable source label"},
            "evidence_path": {"type": "string", "description": "Existing workspace-relative evidence file"},
            "source_location": {"type": "string"},
            "confidence": {"type": "string", "enum": ["current-confirmed", "likely", "unverified", "historical"]},
            "authority": {"type": "string"},
        },
        "required": ["action", "evidence_source", "evidence_path"],
        "additionalProperties": False,
    },
    permission=PermissionClass.WRITE_LOCAL,
    side_effect=SideEffect.UPDATE,
    disclosure=Disclosure.LOCAL_ONLY,
    requires_approval=True,
    idempotent=False,
    previewable=True,
    verifiable=True,
)

ACTION_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="action.propose",
    version=1,
    description=(
        "Propose one workspace change from the Academia action catalog and return its exact preview. "
        "This never performs the change. Inline actions run only after the student presses Allow; "
        "Review actions need a Review decision and a separate verified execute."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": [
                    "task_change",
                    "grade_record",
                    "file_restore",
                    "course_create",
                    "semester_create",
                    "file_move",
                    "file_trash",
                    "configuration_change",
                ],
            },
            "details": {"type": "object", "description": "Exact action fields, for example {\"path\": \"Fall 2026/Course/00_INBOX/file.pdf\"}."},
            "title": {"type": "string", "maxLength": 200},
        },
        "required": ["action_type", "details"],
        "additionalProperties": False,
    },
    permission=PermissionClass.WRITE_LOCAL,
    side_effect=SideEffect.UPDATE,
    disclosure=Disclosure.LOCAL_ONLY,
    requires_approval=True,
    idempotent=False,
    previewable=True,
    verifiable=True,
)


def propose_action(context: "read.ReadContext", arguments: dict[str, Any]) -> ToolResult:
    """Create one catalog action proposal; it never executes the change."""

    from ...action_service import ActionService

    action_type = arguments.get("action_type")
    details = arguments.get("details")
    if not isinstance(action_type, str) or not action_type.strip():
        raise AssistantError("action_type is required", code="invalid_action")
    if not isinstance(details, dict):
        raise AssistantError("details must be a JSON object", code="invalid_action")
    title = arguments.get("title") if isinstance(arguments.get("title"), str) else None
    service = ActionService(config=context.config)
    try:
        created = service.propose(action_type, details, title=title)
    except (ValueError, PermissionError) as exc:
        raise AssistantError(str(exc), code="invalid_action") from exc
    return ToolResult(tool="action.propose", data=created)


WRITE_TOOL_DESCRIPTORS = [IMPORT_PROPOSAL_DESCRIPTOR, STUDY_CREATE_DESCRIPTOR, DOMAIN_CHANGE_DESCRIPTOR, TASK_PROPOSAL_DESCRIPTOR, ACTION_PROPOSAL_DESCRIPTOR]


def _state_stores(root: Path) -> tuple[ApprovalWorkflow, ReviewQueue]:
    state_root = root / ".academia"
    reviews = ReviewQueue(state_root / "review.json")
    workflow = ApprovalWorkflow(
        actions=ActionStore(state_root / "actions.json"),
        reviews=reviews,
        activity=ActivityLog(state_root / "activity.jsonl"),
    )
    return workflow, reviews


def destination_for_target(workspace_root: Path, target_id: str) -> Path:
    if not isinstance(target_id, str) or not target_id.strip() or "\\" in target_id or "\x00" in target_id:
        raise AssistantError("target_id must be an exact workspace-relative inbox id", code="invalid_target")
    relative = PurePosixPath(target_id)
    if relative.is_absolute() or not relative.parts or relative.as_posix() != target_id or relative.parts[-1] != "00_INBOX" or len(relative.parts) not in {2, 3}:
        raise AssistantError("target_id must identify a direct semester or course 00_INBOX", code="invalid_target")
    root = Path(workspace_root).expanduser().resolve()
    destination = root.joinpath(*relative.parts)
    try:
        validate_import_destination(root, destination)
    except ValueError as exc:
        raise AssistantError(str(exc), code="invalid_target") from exc
    return destination


def propose_import(
    context: ReadContext,
    *,
    source_path: str,
    target_id: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Create a Review/Action proposal without copying anything."""
    if not isinstance(source_path, str) or not source_path.strip() or "\x00" in source_path:
        raise AssistantError("source_path must identify one local file", code="invalid_source")
    if source_label is not None and (not isinstance(source_label, str) or not source_label.strip() or "\x00" in source_label):
        raise AssistantError("source_label must be a non-empty string without NUL bytes", code="invalid_source")
    try:
        source = validate_import_source(Path(source_path))
    except (OSError, ValueError) as exc:
        raise AssistantError(str(exc), code="invalid_source") from exc
    if not source.is_file():
        raise AssistantError("source_path must identify a regular local file", code="invalid_source")
    try:
        digest = fingerprint(source, max_bytes=1024 * 1024 * 1024)
    except (OSError, SourceIdentityError) as exc:
        raise AssistantError(str(exc), code="invalid_source") from exc
    destination = destination_for_target(context.root, target_id)
    course_id = PurePosixPath(target_id).parts[1] if len(PurePosixPath(target_id).parts) == 3 else None
    if course_id:
        from ...course_identity import resolve_course_directory
        try:
            resolve_course_directory(context.root, context.semester, course_id)
        except (KeyError, ValueError) as exc:
            raise AssistantError(str(exc), code="invalid_target") from exc
    workflow, _ = _state_stores(context.root)
    effects = [
        f"copy {source.name} into {target_id}",
        "preserve the original source file",
        "record acquisition provenance and a content hash",
        "start supported local extraction without altering the source",
    ]
    proposal, review = workflow.propose(
        action_type=ActionType.FILE_COPY,
        title=f"Import {source.name}",
        details={
            "source_path": str(source),
            "target_id": target_id,
            "destination": str(destination),
            "source_sha256": digest,
            "source_size": source.stat().st_size,
            "effects": effects,
            "source_label": source_label,
        },
        course=course_id,
        priority="normal",
        review_kind="action_approval",
        review_details={
            "filename": source.name,
            "source_path": str(source),
            "proposed_destination": target_id,
            "source_sha256": digest,
            "effects": effects,
        },
    )
    return {
        "status": "approval_required",
        "proposal_id": proposal.id,
        "review_id": review.id,
        "source_path": str(source),
        "source_name": source.name,
        "source_sha256": digest,
        "target_id": target_id,
        "destination": str(destination),
        "effects": effects,
    }


def execute_import_proposal(
    proposal: ActionProposal,
    *,
    workspace_root: Path,
    processing: ProcessingStore | None = None,
) -> dict[str, Any]:
    """Execute an already-approved import and verify the copied file."""
    if proposal.action_type != ActionType.FILE_COPY.value:
        raise ValueError(f"not a file-copy proposal: {proposal.action_type}")
    details = proposal.details if isinstance(proposal.details, dict) else {}
    source_value = details.get("source_path")
    target_id = details.get("target_id")
    expected_digest = details.get("source_sha256")
    if not isinstance(source_value, str) or not isinstance(target_id, str) or not isinstance(expected_digest, str):
        raise ValueError("import proposal is missing its exact source, target, or hash")
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise ValueError("import source no longer exists")
    try:
        current_digest = fingerprint(source, max_bytes=1024 * 1024 * 1024)
    except (OSError, SourceIdentityError) as exc:
        raise ValueError(str(exc)) from exc
    if current_digest != expected_digest:
        raise ValueError("import source changed after approval; create a new proposal")
    destination_inbox = destination_for_target(Path(workspace_root), target_id)
    result = import_file(
        source,
        destination_inbox,
        processing,
        workspace_root=Path(workspace_root),
        source_label=details.get("source_label") if isinstance(details.get("source_label"), str) else None,
    )
    destination = Path(str(result.get("destination", "")))
    if not destination.is_file():
        raise ValueError("import verification failed: destination is missing")
    if fingerprint(destination, max_bytes=1024 * 1024 * 1024) != current_digest:
        raise ValueError("import verification failed: copied content does not match the approved source")
    return {
        "verified": True,
        "destination": str(destination),
        "source_sha256": current_digest,
        "duplicate": bool(result.get("duplicate")),
        "duplicate_of": result.get("duplicate_of"),
        "processing_status": result.get("processing_status"),
    }


def create_study_set(
    context: ReadContext,
    *,
    course: str,
    payload: dict[str, Any],
    source_ids: list[str] | None = None,
    query: str = "",
    pages: str | None = None,
    limit: int = 12,
    deep: bool = False,
    actor: str = "agent:codex",
) -> dict[str, Any]:
    """Create a cited Study set through the canonical Study service."""
    service = StudyService(context.root, context.semester, course)
    study_context = service.context(
        source_ids=source_ids or [],
        query=query,
        pages=pages,
        limit=limit,
        deep=deep,
    )
    created = service.create(payload, study_context, actor=actor)
    return {
        "set": created,
        "coverage": study_context.get("coverage"),
        "warnings": study_context.get("warnings", []),
    }


def propose_domain_change(
    context: ReadContext,
    *,
    course: str,
    entity_type: str,
    entity_id: str,
    field: str,
    after: str,
    evidence_source: str,
    evidence_path: str,
    source_location: str | None = None,
    confidence: str = "unverified",
    authority: str = "unknown",
) -> dict[str, Any]:
    """Create an evidence-backed Review/Action proposal for a derived fact."""
    from ...course_identity import resolve_course_identifier
    try:
        resolved = resolve_course_identifier(context.policy.courses, course)
    except (KeyError, ValueError) as exc:
        raise AssistantError(str(exc), code="unknown_course") from exc
    course_id = str(resolved["id"])
    projection = DomainProjection(context.root / ".academia" / "domain.json")
    current = projection.get(entity_type, entity_id)
    if str(current.get("course_id")) != course_id:
        raise AssistantError("domain entity does not belong to the selected course", code="cross_course_domain")
    if field not in current:
        raise AssistantError(f"domain entity has no field: {field}", code="invalid_domain_field")
    before = current.get(field)
    if str(before) == after:
        raise AssistantError("the proposed value already matches the recorded value", code="no_change")
    if confidence not in {"current-confirmed", "likely", "unverified", "historical"}:
        raise AssistantError("confidence is invalid", code="invalid_evidence")
    try:
        evidence_file = safe_workspace_path(context.root, evidence_path)
    except SourceIdentityError as exc:
        raise AssistantError(str(exc), code="invalid_evidence") from exc
    evidence = asdict(Evidence(
        source=evidence_source,
        source_path=evidence_file.relative_to(context.root).as_posix(),
        source_location=source_location,
        provenance="ORIGINAL",
        confidence=confidence,
        authority=authority,
    ))
    workflow, _ = _state_stores(context.root)
    effects = [
        f"change {field} from {before!s} to {after}",
        "preserve both evidence records in Activity and Review history",
        "verify the derived projection after execution",
    ]
    proposal, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title=f"Review {entity_type} {field} change",
        details={
            "updates": [{
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field": field,
                "before": before,
                "after": after,
                "evidence": evidence,
            }],
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field": field,
            "before": before,
            "after": after,
            "new_evidence": evidence,
            "effects": effects,
        },
        course=course_id,
        priority="high",
        review_kind="domain_conflict",
        review_details={
            "current": before,
            "new": after,
            "field": field,
            "source": evidence_source,
            "confidence": confidence,
            "evidence": evidence,
            "effects": effects,
        },
    )
    return {
        "status": "approval_required",
        "proposal_id": proposal.id,
        "review_id": review.id,
        "before": before,
        "after": after,
        "effects": effects,
    }


_UNSET = object()


def _task_snapshot(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": task.get("title"),
        "course_id": task.get("course_id"),
        "due_date": task.get("due_date"),
        "due_time": task.get("due_time"),
        "status": task.get("status"),
        "updated_at": task.get("updated_at"),
    }


def _task_summary(task: dict[str, Any]) -> str:
    parts = [str(task.get("title", "Untitled task"))]
    if task.get("course_id"):
        parts.append(str(task["course_id"]))
    if task.get("due_date"):
        due = str(task["due_date"])
        if task.get("due_time"):
            due += f" {task['due_time']}"
        parts.append(f"due {due}")
    return " · ".join(parts)


def propose_task_change(
    context: ReadContext,
    *,
    action: str,
    evidence_source: str,
    evidence_path: str,
    task_id: str | None = None,
    title: str | None = None,
    course: str | None = None,
    due_date: Any = _UNSET,
    due_time: Any = _UNSET,
    source_location: str | None = None,
    confidence: str = "unverified",
    authority: str = "unknown",
) -> dict[str, Any]:
    """Create an evidence-backed Review/Action proposal for one personal task."""
    if action not in {"create", "update"}:
        raise AssistantError("task proposals may only create or update a personal task", code="invalid_task_action")
    if not isinstance(evidence_source, str) or not evidence_source.strip() or len(evidence_source) > 120:
        raise AssistantError("evidence_source must be a non-empty label of at most 120 characters", code="invalid_evidence")
    if confidence not in {"current-confirmed", "likely", "unverified", "historical"}:
        raise AssistantError("confidence is invalid", code="invalid_evidence")
    try:
        evidence_file = safe_workspace_path(context.root, evidence_path)
    except SourceIdentityError as exc:
        raise AssistantError(str(exc), code="invalid_evidence") from exc
    if not evidence_file.is_file():
        raise AssistantError("evidence_path must identify an existing workspace file", code="invalid_evidence")
    evidence = asdict(Evidence(
        source=evidence_source,
        source_path=evidence_file.relative_to(context.root).as_posix(),
        source_location=source_location,
        provenance="ORIGINAL",
        confidence=confidence,
        authority=authority,
    ))
    store = TaskStore(context.root, context.semester)
    try:
        if action == "create":
            if not isinstance(title, str) or not title.strip():
                raise AssistantError("creating a task proposal requires a title", code="invalid_task")
            future = store.new_task(
                title=title,
                course_id=course,
                due_date=None if due_date is _UNSET else due_date,
                due_time=None if due_time is _UNSET else due_time,
                provenance="AI-GENERATED",
                source=evidence_source,
            )
            before_task = None
            before_label = "No personal task"
            effects = [
                f"add '{future['title']}' to {context.semester}/SEMESTER_TASKS.md",
                "preserve unrelated Markdown and every existing task",
                "record the new task in Activity",
            ]
        else:
            if not isinstance(task_id, str) or not task_id.strip():
                raise AssistantError("updating a task proposal requires an exact task_id", code="invalid_task")
            before_task = store.get(task_id)
            fields: dict[str, Any] = {}
            if title is not None:
                fields["title"] = title
            if course is not None:
                fields["course_id"] = course
            if due_date is not _UNSET:
                fields["due_date"] = due_date
            if due_time is not _UNSET:
                fields["due_time"] = due_time
            if not fields:
                raise AssistantError("no task fields were provided", code="no_change")
            future = store.preview_update(task_id, **fields)
            if all(future[key] == before_task[key] for key in ("title", "course_id", "due_date", "due_time")):
                raise AssistantError("the proposed task change already matches the recorded task", code="no_change")
            changes = [
                f"{key.replace('_', ' ')}: {before_task.get(key)!s} → {future.get(key)!s}"
                for key in ("title", "course_id", "due_date", "due_time")
                if future.get(key) != before_task.get(key)
            ]
            before_label = _task_summary(before_task)
            effects = [
                *changes,
                "preserve other tasks and unrelated Markdown",
                "record the update in Activity",
            ]
    except TaskStateError as exc:
        raise AssistantError(str(exc), code="invalid_task") from exc
    except KeyError as exc:
        raise AssistantError(f"task not found: {task_id}", code="unknown_task") from exc

    after_label = _task_summary(future)
    workflow, _ = _state_stores(context.root)
    proposal, review = workflow.propose(
        action_type=ActionType.TASK_CHANGE,
        title=f"Add task: {future['title']}" if action == "create" else f"Update task: {future['title']}",
        details={
            "action": action,
            "semester": context.semester,
            "task_file": f"{context.semester}/SEMESTER_TASKS.md",
            "task_id": before_task["id"] if before_task else None,
            "before": before_label,
            "after": after_label,
            "task_before": _task_snapshot(before_task) if before_task else None,
            "task_after": _task_snapshot(future),
            "evidence": evidence,
            "effects": effects,
            "semester_scope": context.semester,
        },
        course=future.get("course_id"),
        priority="normal",
        review_kind="action_approval",
        review_details={
            "question": (
                f"Add this personal task to {context.semester}/SEMESTER_TASKS.md?"
                if action == "create" else "Apply this personal-task update?"
            ),
            "why_this_needs_human_input": "The assistant may propose personal-task changes, but only the student can approve writing to SEMESTER_TASKS.md.",
            "current": before_label,
            "proposed": after_label,
            "source": evidence_source,
            "confidence": confidence,
            "evidence": [evidence_source, evidence["source_path"]],
            "effects": effects,
        },
    )
    return {
        "status": "approval_required",
        "action": action,
        "proposal_id": proposal.id,
        "review_id": review.id,
        "before": before_label,
        "after": after_label,
        "effects": effects,
    }


def execute_task_change(proposal: ActionProposal, *, workspace_root: Path) -> dict[str, Any]:
    """Execute one approved create/update against the canonical task file."""
    if proposal.action_type != ActionType.TASK_CHANGE.value:
        raise ValueError(f"not a task-change proposal: {proposal.action_type}")
    details = proposal.details if isinstance(proposal.details, dict) else {}
    semester = details.get("semester")
    action = details.get("action")
    after = details.get("task_after")
    if not isinstance(semester, str) or action not in {"create", "update"} or not isinstance(after, dict):
        raise ValueError("task proposal is missing its semester, action, or proposed task")
    store = TaskStore(Path(workspace_root), semester)
    evidence = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
    try:
        if action == "create":
            if not isinstance(after.get("title"), str):
                raise ValueError("task proposal is missing its title")
            created = store.create(
                title=after["title"],
                course_id=after.get("course_id") if isinstance(after.get("course_id"), str) else None,
                due_date=after.get("due_date") if isinstance(after.get("due_date"), str) else None,
                due_time=after.get("due_time") if isinstance(after.get("due_time"), str) else None,
                provenance="AI-GENERATED",
                source=str(evidence.get("source") or "assistant"),
                actor="agent:review",
            )
            for key in ("title", "course_id", "due_date", "due_time"):
                if created.get(key) != after.get(key):
                    raise ValueError("task verification failed after creation")
            return {
                "verified": True,
                "action": "create",
                "task": created,
                "task_file": str(store.path),
                "effects": details.get("effects", []),
            }
        task_id = details.get("task_id")
        before = details.get("task_before")
        if not isinstance(task_id, str) or not isinstance(before, dict):
            raise ValueError("task update proposal is missing its exact task")
        current = store.get(task_id)
        if current.get("updated_at") != before.get("updated_at"):
            raise ValueError("the personal task changed after approval; create a new proposal")
        updated = store.update(
            task_id,
            title=after.get("title"),
            course_id=after.get("course_id") if isinstance(after.get("course_id"), str) else None,
            due_date=after.get("due_date") if isinstance(after.get("due_date"), str) else None,
            due_time=after.get("due_time") if isinstance(after.get("due_time"), str) else None,
            actor="agent:review",
        )
        for key in ("title", "course_id", "due_date", "due_time"):
            if updated.get(key) != after.get(key):
                raise ValueError("task verification failed after update")
        return {
            "verified": True,
            "action": "update",
            "task": updated,
            "task_file": str(store.path),
            "effects": details.get("effects", []),
        }
    except TaskStateError as exc:
        raise ValueError(str(exc)) from exc
    except KeyError as exc:
        raise ValueError("the personal task no longer exists") from exc


def amend_task_proposal(
    review_id: str,
    *,
    workspace_root: Path,
    title: str | None = None,
    course_id: Any = ...,
    due_date: Any = ...,
    due_time: Any = ...,
    actor: str = "user",
) -> ReviewItem:
    """Edit one proposed personal-task action before the student decides."""
    state_root = Path(workspace_root).expanduser().resolve() / ".academia"
    reviews = ReviewQueue(state_root / "review.json")
    actions = ActionStore(state_root / "actions.json")
    activity = ActivityLog(state_root / "activity.jsonl")
    review = reviews.get(review_id)
    if review.status is not ReviewStatus.OPEN:
        raise ValueError("only an open Review item can be amended")
    if not review.action_proposal_id:
        raise ValueError("Review item has no linked action proposal")
    proposal = actions.get(review.action_proposal_id)
    if proposal.action_type != ActionType.TASK_CHANGE.value:
        raise ValueError("only personal-task proposals can be amended")
    if proposal.status != "proposed":
        raise ValueError("only an unapproved proposal can be amended")
    details = dict(proposal.details)
    action = details.get("action")
    semester = details.get("semester")
    after = details.get("task_after") if isinstance(details.get("task_after"), dict) else {}
    evidence = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
    if action not in {"create", "update"} or not isinstance(semester, str):
        raise ValueError("task proposal is missing its action or semester")

    desired_title = title if title is not None else after.get("title")
    desired_course = course_id if course_id is not ... else after.get("course_id")
    desired_due_date = due_date if due_date is not ... else after.get("due_date")
    desired_due_time = due_time if due_time is not ... else after.get("due_time")
    if desired_due_date in {None, ""}:
        desired_due_time = None
    store = TaskStore(workspace_root, semester)
    try:
        if action == "create":
            future = store.new_task(
                title=desired_title,
                course_id=desired_course if isinstance(desired_course, str) else None,
                due_date=desired_due_date,
                due_time=desired_due_time,
                provenance="AI-GENERATED",
                source=str(evidence.get("source") or "assistant"),
            )
            before_task = None
            before_label = str(details.get("before") or "No personal task")
            effects = [
                f"add '{future['title']}' to {semester}/SEMESTER_TASKS.md",
                "preserve unrelated Markdown and every existing task",
                "record the new task in Activity",
            ]
        else:
            task_id = details.get("task_id")
            before_task = details.get("task_before") if isinstance(details.get("task_before"), dict) else None
            if not isinstance(task_id, str) or before_task is None:
                raise ValueError("task update proposal is missing its exact task")
            current = store.get(task_id)
            if current.get("updated_at") != before_task.get("updated_at"):
                raise ValueError("the personal task changed after the proposal; create a new proposal")
            future = store.preview_update(
                task_id,
                title=desired_title,
                course_id=desired_course if isinstance(desired_course, str) else None,
                due_date=desired_due_date,
                due_time=desired_due_time,
            )
            before_label = str(details.get("before") or _task_summary(before_task))
            changes = [
                f"{key.replace('_', ' ')}: {before_task.get(key)!s} → {future.get(key)!s}"
                for key in ("title", "course_id", "due_date", "due_time")
                if future.get(key) != before_task.get(key)
            ]
            effects = [
                *changes,
                "preserve other tasks and unrelated Markdown",
                "record the update in Activity",
            ]
    except TaskStateError as exc:
        raise ValueError(str(exc)) from exc
    except KeyError as exc:
        raise ValueError("the personal task no longer exists") from exc

    if all(future.get(key) == after.get(key) for key in ("title", "course_id", "due_date", "due_time")):
        raise ValueError("the proposal already matches these values")
    after_label = _task_summary(future)
    new_details = {
        **details,
        "before": before_label,
        "after": after_label,
        "task_after": _task_snapshot(future),
        "effects": effects,
    }
    old_details = details
    old_title = proposal.title
    proposal_title = f"Add task: {future['title']}" if action == "create" else f"Update task: {future['title']}"
    actions.amend(proposal.id, new_details, title=proposal_title)
    try:
        review_details = dict(review.details)
        review_details.update({
            "proposal_details": new_details,
            "current": before_label,
            "proposed": after_label,
            "effects": effects,
        })
        updated_review = reviews.update(
            review.id,
            title=proposal_title,
            details=review_details,
        )
    except Exception:
        actions.amend(proposal.id, old_details, title=old_title)
        raise
    activity.append(
        event_type="action.amended",
        title=f"Amended proposal: {future['title']}",
        course=future.get("course_id"),
        details={"proposal_id": proposal.id, "review_id": review.id, "effects": effects},
        actor=actor,
    )
    return updated_review
