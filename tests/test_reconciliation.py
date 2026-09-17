from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from academia_os.actions import ActionStore, ActionStatus, ActionType
from academia_os.activity import ActivityLog
from academia_os.domain import DomainProjection
from academia_os.extraction import extract_syllabus
from academia_os.extraction.reconcile import execute_domain_change, reconcile_syllabus
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.workflow import ApprovalWorkflow


COURSE = "POL 3124 - Politics and Society"


def _syllabus(path: Path, deadline: str) -> Path:
    path.write_text(
        f"""# {COURSE}
Course: {COURSE}

## Assessments
- Research Essay — 25% — Due {deadline}

## Required Readings
- Smith, John. Politics Today, 3rd ed., Chapter 2, pp. 10-20

## Course Meetings
- Monday 10:00 AM - 11:30 AM, Room 201
""",
        encoding="utf-8",
    )
    return path


def _workflow(tmp_path: Path) -> tuple[DomainProjection, ReviewQueue, ActionStore, ActivityLog, ApprovalWorkflow]:
    domain = DomainProjection(tmp_path / ".academia" / "domain.json")
    reviews = ReviewQueue(tmp_path / ".academia" / "review.json")
    actions = ActionStore(tmp_path / ".academia" / "actions.json")
    activity = ActivityLog(tmp_path / ".academia" / "activity.jsonl")
    return domain, reviews, actions, activity, ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity)


def test_reconciliation_preview_does_not_mutate_domain_or_review_state(tmp_path: Path) -> None:
    source = _syllabus(tmp_path / "syllabus.md", "October 19, 2026")
    extraction = extract_syllabus(source, course_id=COURSE, verified_current=True)
    domain, reviews, actions, _activity, workflow = _workflow(tmp_path)

    preview = reconcile_syllabus(extraction, domain=domain, workflow=workflow, apply=False)

    assert preview.applied is False
    assert preview.added_count >= 4
    assert domain.list() == []
    assert reviews.list(include_resolved=True) == []
    assert actions.list() == []


def test_reconciliation_adds_evidence_backed_entities_and_repeat_is_idempotent(tmp_path: Path) -> None:
    source = _syllabus(tmp_path / "syllabus.md", "October 19, 2026")
    extraction = extract_syllabus(source, course_id=COURSE, verified_current=True)
    domain, reviews, _actions, _activity, workflow = _workflow(tmp_path)

    first = reconcile_syllabus(extraction, domain=domain, workflow=workflow, apply=True)
    second = reconcile_syllabus(extraction, domain=domain, workflow=workflow, apply=True)

    assert first.applied is True
    assert first.added_count > 0
    assert second.duplicate_count == len(extraction.candidates)
    assert len(domain.list("assignment")) == 1
    assert len(domain.list("deadline")) == 1
    assert len(domain.list("reading")) == 1
    assert len(domain.list("course_meeting")) == 1
    assert reviews.list(include_resolved=True) == []


def test_conflicting_deadline_creates_typed_review_and_domain_change_proposal(tmp_path: Path) -> None:
    first_path = _syllabus(tmp_path / "first.md", "October 19, 2026")
    second_path = _syllabus(tmp_path / "second.md", "October 22, 2026")
    domain, reviews, actions, _activity, workflow = _workflow(tmp_path)
    reconcile_syllabus(extract_syllabus(first_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)

    result = reconcile_syllabus(extract_syllabus(second_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)

    assert result.conflict_count == 1
    review = reviews.list()[0]
    assert review.kind == "deadline_conflict"
    assert review.details["assignment"] == "Research Essay"
    assert review.details["current"] == "2026-10-19"
    assert review.details["new"] == "2026-10-22"
    assert review.details["new_evidence"]["source_path"].endswith("second.md")
    proposal = actions.get(review.action_proposal_id or "")
    assert proposal.action_type == ActionType.DOMAIN_CHANGE.value
    assert proposal.status == ActionStatus.PROPOSED.value
    assert proposal.details["field"] == "deadline"


def test_keep_current_rejects_domain_change_and_use_new_executes_and_rereads(tmp_path: Path) -> None:
    first_path = _syllabus(tmp_path / "first.md", "October 19, 2026")
    second_path = _syllabus(tmp_path / "second.md", "October 22, 2026")
    domain, reviews, actions, activity, workflow = _workflow(tmp_path)
    reconcile_syllabus(extract_syllabus(first_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    reconcile_syllabus(extract_syllabus(second_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    review = reviews.list()[0]
    proposal_id = review.action_proposal_id or ""

    workflow.decide_review(review.id, "keep_current")

    assert actions.get(proposal_id).status == ActionStatus.REJECTED.value
    assert domain.list("assignment")[0]["deadline"] == "2026-10-19"

    # A fresh conflict demonstrates the approved/executed path without mutating from React or Review directly.
    third_path = _syllabus(tmp_path / "third.md", "October 24, 2026")
    reconcile_syllabus(extract_syllabus(third_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    next_review = reviews.list()[0]
    proposal = actions.get(next_review.action_proposal_id or "")
    workflow.decide_review(next_review.id, "use_new")
    verified = workflow.execute_approved(proposal.id, lambda item: execute_domain_change(item, domain))

    assert verified.status == ActionStatus.VERIFIED.value
    assert domain.list("assignment")[0]["deadline"] == "2026-10-24"
    assert reviews.get(next_review.id).status is ReviewStatus.RESOLVED
    assert activity.list(limit=1)[0].event_type == "action.verified"


def test_domain_change_failure_marks_action_failed_reopens_review_and_preserves_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_path = _syllabus(tmp_path / "first.md", "October 19, 2026")
    second_path = _syllabus(tmp_path / "second.md", "October 22, 2026")
    domain, reviews, actions, activity, workflow = _workflow(tmp_path)
    reconcile_syllabus(extract_syllabus(first_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    reconcile_syllabus(extract_syllabus(second_path, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    review = reviews.list()[0]
    proposal = actions.get(review.action_proposal_id or "")
    workflow.decide_review(review.id, "use_new")

    original_get = domain.get
    calls = {"count": 0}
    update_count = len(proposal.details["updates"])

    def fail_on_verification(entity_type: str, entity_id: str):
        calls["count"] += 1
        value = original_get(entity_type, entity_id)
        if calls["count"] > update_count:
            value["deadline" if entity_type == "assignment" else "date"] = "wrong-readback"
        return value

    monkeypatch.setattr(domain, "get", fail_on_verification)
    try:
        workflow.execute_approved(proposal.id, lambda item: execute_domain_change(item, domain))
    except (RuntimeError, ValueError):
        pass

    assert actions.get(proposal.id).status == ActionStatus.FAILED.value
    assert reviews.get(review.id).status is ReviewStatus.OPEN
    monkeypatch.setattr(domain, "get", original_get)
    assignment = domain.list("assignment")[0]
    assert original_get("assignment", assignment["id"])["deadline"] == "2026-10-19"
    assert activity.list(limit=1)[0].event_type == "action.failed"


def test_assignment_nullable_fields_are_enriched_without_erasing_existing_values(tmp_path: Path) -> None:
    first = tmp_path / "partial.md"
    first.write_text("Course: POL 3124 - Politics\n## Assessments\n- Research Essay — Due October 19, 2026\n", encoding="utf-8")
    second = _syllabus(tmp_path / "complete.md", "October 19, 2026")
    domain, _reviews, _actions, _activity, workflow = _workflow(tmp_path)

    reconcile_syllabus(extract_syllabus(first, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)
    reconcile_syllabus(extract_syllabus(second, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)

    assignment = domain.list("assignment")[0]
    assert assignment["deadline"] == "2026-10-19"
    assert assignment["weight"] == "25%"


def test_reconciliation_rejects_candidate_evidence_from_operational_state(tmp_path: Path) -> None:
    source = _syllabus(tmp_path / "syllabus.md", "October 19, 2026")
    extraction = extract_syllabus(source, course_id=COURSE, verified_current=True)
    candidate = extraction.candidates[0]
    unsafe_evidence = replace(candidate.evidence, source_path=str(tmp_path / ".academia" / "domain.json"))
    unsafe = replace(candidate, evidence=unsafe_evidence)
    unsafe_extraction = replace(extraction, candidates=(unsafe,))
    domain, _reviews, _actions, _activity, workflow = _workflow(tmp_path)

    with pytest.raises(ValueError, match="operational state"):
        reconcile_syllabus(unsafe_extraction, domain=domain, workflow=workflow, apply=True)

    assert domain.list() == []


def test_identity_mismatch_creates_course_uncertainty_review_without_domain_mutation(tmp_path: Path) -> None:
    source = tmp_path / "wrong.md"
    source.write_text("Course: POL 9999 - Other Course\n## Assessments\n- Essay — 20% — Due October 19, 2026\n", encoding="utf-8")
    domain, reviews, actions, _activity, workflow = _workflow(tmp_path)

    result = reconcile_syllabus(extract_syllabus(source, course_id=COURSE, verified_current=True), domain=domain, workflow=workflow, apply=True)

    assert result.conflict_count == 0
    assert actions.list() == []
    assert reviews.list()[0].kind == "course_identity_uncertainty"
    assert domain.list() == []
