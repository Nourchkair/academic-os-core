from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from ..actions import ActionProposal, ActionType
from ..domain import AcademicSource, Announcement, Assignment, CourseMeeting, Deadline, DomainProjection, Entity, Evidence, Reading
from ..workflow import ApprovalWorkflow
from .models import CandidateFact, ExtractionResult, ExtractionStatus


@dataclass
class ReconciliationResult:
    applied: bool
    added_count: int = 0
    duplicate_count: int = 0
    conflict_count: int = 0
    warnings: list[str] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _entity_from_candidate(candidate: CandidateFact, *, entity_id: str | None = None) -> Entity:
    data = dict(candidate.entity)
    data["id"] = entity_id or data["id"]
    data["evidence"] = candidate.evidence
    constructors = {
        "academic_source": AcademicSource,
        "deadline": Deadline,
        "assignment": Assignment,
        "reading": Reading,
        "announcement": Announcement,
        "course_meeting": CourseMeeting,
    }
    constructor = constructors.get(candidate.entity_type)
    if constructor is None:
        raise ValueError(f"unsupported extraction entity type: {candidate.entity_type}")
    return constructor(**data)


def _find_existing(domain: DomainProjection, candidate: CandidateFact) -> dict[str, Any] | None:
    course_id = candidate.entity.get("course_id")
    title = _norm(candidate.entity.get("title"))
    values = domain.list(candidate.entity_type)
    for value in values:
        if _norm(value.get("course_id")) != _norm(course_id):
            continue
        if _norm(value.get("title")) == title:
            return value
    return None


def _find_deadline(domain: DomainProjection, course_id: str, title: str) -> dict[str, Any] | None:
    for value in domain.list("deadline"):
        if _norm(value.get("course_id")) == _norm(course_id) and _norm(value.get("title")) == _norm(title):
            return value
    return None


def _conflict_fingerprint(candidate: CandidateFact, existing: dict[str, Any], field: str) -> str:
    payload = {
        "entity_type": candidate.entity_type,
        "entity_id": existing.get("id"),
        "field": field,
        "before": existing.get(field),
        "after": candidate.entity.get(field),
        "new_source": candidate.evidence.source_hash or candidate.evidence.source_path,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _existing_review(workflow: ApprovalWorkflow, fingerprint: str):
    for item in workflow.reviews.list(include_resolved=True):
        if item.details.get("fingerprint") == fingerprint and item.status.value == "open":
            return item
    return None


def _make_conflict(workflow: ApprovalWorkflow, domain: DomainProjection, candidate: CandidateFact, existing: dict[str, Any], field: str, result: ReconciliationResult) -> None:
    fingerprint = _conflict_fingerprint(candidate, existing, field)
    details = {
        "fingerprint": fingerprint,
        "assignment": existing.get("title") or candidate.entity.get("title"),
        "current": existing.get(field),
        "new": candidate.entity.get(field),
        "source": candidate.evidence.source,
        "confidence": candidate.confidence,
        "current_evidence": existing.get("evidence"),
        "new_evidence": asdict(candidate.evidence),
        "entity_type": existing.get("entity_type", candidate.entity_type),
        "entity_id": existing.get("id"),
        "field": field,
        "before": existing.get(field),
        "after": candidate.entity.get(field),
        "effects": [
            f"change {field} from {existing.get(field)} to {candidate.entity.get(field)}",
            "preserve both evidence records in Activity and Review history",
            "reread .academia/domain.json before marking the action verified",
        ],
    }
    updates = [{
        "entity_type": existing.get("entity_type", candidate.entity_type),
        "entity_id": existing.get("id"),
        "field": field,
        "before": existing.get(field),
        "after": candidate.entity.get(field),
        "evidence": asdict(candidate.evidence),
    }]
    related_deadline = None
    if candidate.entity_type == "assignment" and field == "deadline":
        related_deadline = _find_deadline(domain, str(candidate.entity.get("course_id")), str(candidate.entity.get("title")))
    if related_deadline:
        updates.append({
            "entity_type": "deadline",
            "entity_id": related_deadline["id"],
            "field": "date",
            "before": related_deadline.get("date"),
            "after": candidate.entity.get("deadline"),
            "evidence": asdict(candidate.evidence),
        })
    details["updates"] = updates
    if _existing_review(workflow, fingerprint):
        result.warnings.append(f"Existing open Review retained for {candidate.entity.get('title')} {field} conflict.")
        return
    proposal, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title=f"Review {candidate.entity.get('title')} {field}",
        details=details,
        course=str(candidate.entity.get("course_id")),
        priority="high",
        review_kind="deadline_conflict" if field == "deadline" else "domain_conflict",
        review_details=details,
    )
    result.reviews.append(asdict(review))
    result.actions.append(asdict(proposal))


def _reconcile_candidate(candidate: CandidateFact, domain: DomainProjection, workflow: ApprovalWorkflow, *, apply: bool, result: ReconciliationResult, conflict_keys: set[tuple[str, str]]) -> None:
    existing = _find_existing(domain, candidate)
    if existing is None:
        if apply:
            domain.upsert(_entity_from_candidate(candidate))
        result.added_count += 1
        return
    if candidate.entity_type == "assignment":
        for field in ("deadline", "weight"):
            before = existing.get(field)
            after = candidate.entity.get(field)
            if before is not None and after is not None and before != after:
                conflict_keys.add((_norm(existing.get("title")), field))
                result.conflict_count += 1
                if apply:
                    _make_conflict(workflow, domain, candidate, existing, field, result)
                return
        merged = dict(existing)
        merged.pop("entity_type", None)
        changed = False
        for field in ("deadline", "weight"):
            if merged.get(field) is None and candidate.entity.get(field) is not None:
                merged[field] = candidate.entity[field]
                changed = True
        if changed and apply:
            domain.upsert(_entity_from_candidate(replace(candidate, entity=merged), entity_id=str(existing["id"])))
        result.duplicate_count += 1
        return
    field = "date" if candidate.entity_type == "deadline" else None
    if field and existing.get(field) != candidate.entity.get(field):
        key = (_norm(existing.get("title")), "deadline")
        if key in conflict_keys:
            result.duplicate_count += 1
            return
        result.conflict_count += 1
        if apply:
            _make_conflict(workflow, domain, candidate, existing, field, result)
        return
    result.duplicate_count += 1


def _identity_review(extraction: ExtractionResult, workflow: ApprovalWorkflow, course_id: str, result: ReconciliationResult) -> None:
    fingerprint = hashlib.sha256(f"course-identity:{extraction.source.content_hash}:{course_id}".encode("utf-8")).hexdigest()
    if _existing_review(workflow, fingerprint):
        result.warnings.append("Existing open Review retained for the syllabus course identity mismatch.")
        return
    identity = next((candidate for candidate in extraction.candidates if candidate.kind == "course_identity"), None)
    metadata = identity.entity.get("metadata", {}) if identity else {}
    review = workflow.reviews.add(
        kind="course_identity_uncertainty",
        title=f"Verify syllabus course identity: {Path(extraction.source.path).name}",
        course=course_id,
        priority="high",
        details={
            "fingerprint": fingerprint,
            "supplied_course": course_id,
            "detected_course_code": metadata.get("detected_course_code"),
            "detected_course_title": metadata.get("detected_course_title"),
            "source": Path(extraction.source.path).name,
            "source_path": extraction.source.path,
            "confidence": "unverified",
            "effects": ["no domain facts were added", "choose the correct course context before applying syllabus facts"],
        },
    )
    workflow.activity.append(
        event_type="review.created",
        title=review.title,
        course=course_id,
        source=extraction.source.path,
        confidence="unverified",
        details={"review_id": review.id, "kind": review.kind},
        actor="system",
    )
    result.reviews.append(asdict(review))


def _validate_candidate(candidate: CandidateFact) -> None:
    if not candidate.evidence.source_path.strip():
        raise ValueError("candidate evidence.source_path is required")
    if ".academia" in Path(candidate.evidence.source_path).expanduser().parts:
        raise ValueError("candidate evidence cannot point to operational state")
    if not candidate.entity.get("course_id"):
        raise ValueError("candidate course_id is required")
    if candidate.confidence not in {"current-confirmed", "likely", "unverified", "historical"}:
        raise ValueError("candidate confidence is invalid")
    if candidate.evidence.provenance not in {"ORIGINAL", "USER-CREATED", "AI-GENERATED", "EXTERNAL"}:
        raise ValueError("candidate provenance is invalid")
    _entity_from_candidate(candidate)


def reconcile_syllabus(extraction: ExtractionResult, *, domain: DomainProjection, workflow: ApprovalWorkflow, apply: bool) -> ReconciliationResult:
    if extraction.source_type != "syllabus":
        raise ValueError("only syllabus extraction can be reconciled by this service")
    result = ReconciliationResult(applied=apply, warnings=list(extraction.warnings))
    if extraction.status is not ExtractionStatus.SUPPORTED:
        result.warnings.append(f"Extraction was not applied: {extraction.status.value}")
        return result
    for candidate in extraction.candidates:
        _validate_candidate(candidate)
    if extraction.identity_status == "mismatch":
        result.warnings.append("Syllabus facts remain uncommitted until the course identity is resolved.")
        if apply:
            _identity_review(extraction, workflow, str(extraction.candidates[0].entity.get("course_id", "")), result)
        return result
    if not apply and not domain.path.exists():
        result.added_count = len(extraction.candidates)
        return result
    conflict_keys: set[tuple[str, str]] = set()
    for candidate in extraction.candidates:
        _reconcile_candidate(candidate, domain, workflow, apply=apply, result=result, conflict_keys=conflict_keys)
    return result


def execute_domain_change(proposal: ActionProposal, domain: DomainProjection) -> dict[str, Any]:
    if proposal.action_type != ActionType.DOMAIN_CHANGE.value:
        raise ValueError(f"not a domain change proposal: {proposal.action_type}")
    details = proposal.details
    updates = details.get("updates")
    if not isinstance(updates, list) or not updates:
        updates = [{
            "entity_type": details.get("entity_type"),
            "entity_id": details.get("entity_id"),
            "field": details.get("field"),
            "before": details.get("before"),
            "after": details.get("after"),
            "evidence": details.get("new_evidence"),
        }]
    snapshots: list[tuple[str, str, dict[str, Any]]] = []
    try:
        for update in updates:
            entity_type = str(update.get("entity_type"))
            entity_id = str(update.get("entity_id"))
            current = domain.get(entity_type, entity_id)
            snapshots.append((entity_type, entity_id, current))
            domain.update_field(
                entity_type,
                entity_id,
                str(update.get("field")),
                update.get("after"),
                expected_before=update.get("before"),
                evidence=update.get("evidence"),
            )
        reread: list[dict[str, Any]] = []
        for update in updates:
            stored = domain.get(str(update.get("entity_type")), str(update.get("entity_id")))
            if stored.get(str(update.get("field"))) != update.get("after"):
                raise ValueError("domain change verification readback did not match the approved value")
            reread.append({"entity_type": update.get("entity_type"), "entity_id": update.get("entity_id"), "field": update.get("field"), "value": stored.get(str(update.get("field")))})
    except Exception:
        for entity_type, entity_id, previous in reversed(snapshots):
            domain.replace_raw(entity_type, entity_id, previous)
        raise
    return {"verified": True, "reread": reread, "proposal_id": proposal.id}
