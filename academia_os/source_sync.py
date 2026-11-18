"""Preview or apply a syllabus source through the existing reconciliation engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionStore
from .activity import ActivityLog
from .course_identity import resolve_course_identifier
from .domain import DomainProjection
from .extraction.reconcile import reconcile_syllabus
from .extraction.syllabus import extract_syllabus
from .review import ReviewQueue
from .source_identity import fingerprint, validate_source_id
from .workflow import ApprovalWorkflow


def sync_syllabus(config: dict[str, Any], snapshot: dict[str, Any], *, course_id: str, source_id: str, verified_current: bool = False, apply: bool = False) -> dict[str, Any]:
    resolved = resolve_course_identifier(snapshot.get("courses", []), course_id)
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    semester = str(snapshot["semester"])
    source = validate_source_id(root, source_id, semester=semester)
    if not source_id.startswith(f"{semester}/{resolved['id']}/"):
        raise ValueError("syllabus source must belong to the selected course")
    extraction = extract_syllabus(source, course_id=str(resolved["id"]), verified_current=verified_current)
    state_root = root / ".academia"
    workflow = ApprovalWorkflow(
        actions=ActionStore(state_root / "actions.json"),
        reviews=ReviewQueue(state_root / "review.json"),
        activity=ActivityLog(state_root / "activity.jsonl"),
        courses=snapshot.get("courses", []),
    )
    reconciliation = reconcile_syllabus(
        extraction,
        domain=DomainProjection(state_root / "domain.json"),
        workflow=workflow,
        apply=apply,
    )
    return {
        "schema_version": 1,
        "status": "applied" if apply else "preview",
        "course_id": resolved["id"],
        "source": source_id,
        "source_hash": fingerprint(source),
        "extraction": {
            "status": extraction.status.value,
            "source_type": extraction.source_type,
            "candidate_count": len(extraction.candidates),
            "identity_status": extraction.identity_status,
            "warnings": list(extraction.warnings),
            "unsupported": list(extraction.unsupported),
        },
        "reconciliation": reconciliation.as_dict(),
        "next_step": (
            "Review the created Review items and approve any change before it is executed."
            if apply and (reconciliation.reviews or reconciliation.actions)
            else "Run again with --apply to add safe projections and create Review items for conflicts."
            if not apply
            else "No Review items were created. The projection was already current or the source had no supported candidates."
        ),
    }
