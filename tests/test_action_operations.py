from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from academia_os.actions import ActionStatus, ActionStore, ActionType
from academia_os.activity import ActivityLog
from academia_os.domain import Deadline, DomainProjection, Evidence
from academia_os.extraction.reconcile import execute_domain_change
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.workflow import ApprovalWorkflow


def workflow_for(tmp_path: Path) -> tuple[ApprovalWorkflow, ActionStore, ReviewQueue, ActivityLog]:
    actions = ActionStore(tmp_path / "actions.json")
    reviews = ReviewQueue(tmp_path / "review.json")
    activity = ActivityLog(tmp_path / "activity.jsonl")
    return ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity), actions, reviews, activity


def test_proposal_and_review_share_operation_identity(tmp_path: Path) -> None:
    workflow, actions, reviews, _ = workflow_for(tmp_path)
    proposal, review = workflow.propose(action_type=ActionType.CALENDAR_CHANGE, title="Add midterm", details={"date": "2026-10-21"})

    operation = proposal.details["operation"]
    assert operation["id"]
    assert operation["phase"] == "proposed"
    assert operation["attempts"] == 0
    assert review.details["operation_id"] == operation["id"]
    assert review.details["operation_phase"] == "proposed"
    assert actions.get(proposal.id).details["operation"]["id"] == operation["id"]


def test_approval_execution_and_verification_update_the_same_operation(tmp_path: Path) -> None:
    workflow, actions, reviews, activity = workflow_for(tmp_path)
    proposal, review = workflow.propose(action_type=ActionType.CALENDAR_CHANGE, title="Add midterm", details={"date": "2026-10-21"})
    operation_id = proposal.details["operation"]["id"]

    workflow.approve_review(review.id)
    approved = actions.get(proposal.id)
    assert approved.status == ActionStatus.APPROVED.value
    assert approved.details["operation"]["phase"] == "approved"
    assert reviews.get(review.id).details["operation_phase"] == "approved"

    verified = workflow.execute_approved(proposal.id, lambda item: {"verified": True, "operation_id": item.details["operation"]["id"]})
    assert verified.status == ActionStatus.VERIFIED.value
    stored = actions.get(proposal.id)
    assert stored.details["operation"]["id"] == operation_id
    assert stored.details["operation"]["phase"] == "verified"
    assert stored.details["operation"]["attempts"] == 1
    resolved = reviews.get(review.id)
    assert resolved.status is ReviewStatus.RESOLVED
    assert resolved.details["operation_id"] == operation_id
    assert resolved.details["operation_phase"] == "verified"
    assert activity.list(limit=1)[0].event_type == "action.verified"


def test_verified_actions_cannot_be_replayed(tmp_path: Path) -> None:
    workflow, _, _, _ = workflow_for(tmp_path)
    proposal, review = workflow.propose(action_type=ActionType.CALENDAR_CHANGE, title="Add midterm")
    workflow.approve_review(review.id)
    workflow.execute_approved(proposal.id, lambda item: {"verified": True})

    calls = 0

    def executor(item):
        nonlocal calls
        calls += 1
        return {"verified": True}

    with pytest.raises(ValueError, match="already verified"):
        workflow.execute_approved(proposal.id, executor)
    assert calls == 0


def test_interrupted_execution_can_resume_once(tmp_path: Path) -> None:
    workflow, actions, reviews, activity = workflow_for(tmp_path)
    proposal, review = workflow.propose(action_type=ActionType.DOMAIN_CHANGE, title="Update deadline")
    workflow.approve_review(review.id)

    # Simulate a process death after execution began but before verification.
    started = actions.begin_execution(proposal.id)
    assert started.status == ActionStatus.EXECUTED.value
    assert started.details["operation"]["phase"] == "executing"
    assert started.details["operation"]["attempts"] == 1

    resumed = workflow.execute_approved(proposal.id, lambda item: {"verified": True, "attempt": item.details["operation"]["attempts"]})
    assert resumed.status == ActionStatus.VERIFIED.value
    assert actions.get(proposal.id).details["operation"]["attempts"] == 2
    assert reviews.get(review.id).status is ReviewStatus.RESOLVED
    assert any(event.event_type == "action.execution_resumed" for event in activity.list(limit=10))


def test_failed_execution_reopens_review_and_cannot_be_replayed_automatically(tmp_path: Path) -> None:
    workflow, actions, reviews, activity = workflow_for(tmp_path)
    proposal, review = workflow.propose(action_type=ActionType.CALENDAR_CHANGE, title="Add midterm")
    workflow.approve_review(review.id)

    def fail(item):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        workflow.execute_approved(proposal.id, fail)

    failed = actions.get(proposal.id)
    assert failed.status == ActionStatus.FAILED.value
    assert failed.details["operation"]["phase"] == "failed"
    assert failed.failure_reason == "provider unavailable"
    assert reviews.get(review.id).status is ReviewStatus.OPEN
    assert reviews.get(review.id).details["operation_phase"] == "failed"
    assert activity.list(limit=1)[0].event_type == "action.failed"

    with pytest.raises(ValueError, match="not executable"):
        workflow.execute_approved(proposal.id, lambda item: {"verified": True})


def test_domain_change_retry_after_commit_is_idempotent(tmp_path: Path) -> None:
    workflow, actions, reviews, _ = workflow_for(tmp_path)
    domain = DomainProjection(tmp_path / "domain.json")
    evidence = Evidence(
        source="Syllabus",
        source_path="Fall 2026/POL 2103 - Politics/01_COURSE/syllabus.md",
        provenance="ORIGINAL",
        confidence="current-confirmed",
        authority="course syllabus",
    )
    domain.upsert(Deadline(
        id="essay",
        course_id="POL 2103 - Politics",
        title="Research Essay",
        date="2026-10-19",
        time=None,
        type="assignment",
        evidence=evidence,
    ))
    proposal, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title="Update Research Essay deadline",
        details={
            "updates": [{
                "entity_type": "deadline",
                "entity_id": "essay",
                "field": "date",
                "before": "2026-10-19",
                "after": "2026-10-22",
                "evidence": asdict(evidence),
            }]
        },
    )
    workflow.approve_review(review.id)
    # Simulate a crash after the first executor committed the new value but
    # before the verification step recorded completion.
    domain.update_field("deadline", "essay", "date", "2026-10-22", expected_before="2026-10-19", evidence=asdict(evidence))

    verified = workflow.execute_approved(proposal.id, lambda item: execute_domain_change(item, domain))
    assert verified.status == ActionStatus.VERIFIED.value
    result = execute_domain_change(actions.get(proposal.id), domain)
    assert result["verified"] is True
    assert result["already_applied"]
    assert domain.get("deadline", "essay")["date"] == "2026-10-22"
