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
from ...review import ReviewQueue
from ...source_identity import SourceIdentityError, fingerprint, safe_workspace_path
from ...study import StudyService
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

WRITE_TOOL_DESCRIPTORS = [IMPORT_PROPOSAL_DESCRIPTOR, STUDY_CREATE_DESCRIPTOR, DOMAIN_CHANGE_DESCRIPTOR]


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
