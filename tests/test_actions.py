from pathlib import Path

import pytest

from academia_os.activity import ActivityLog
from academia_os.actions import ActionStatus, ActionStore, ActionType
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.workflow import ApprovalWorkflow


def test_action_proposal_requires_explicit_approval_and_verification(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.json")
    proposal = store.propose(action_type=ActionType.CALENDAR_CHANGE, title="Add midterm", details={"date": "2026-10-21"})
    assert proposal.status == ActionStatus.PROPOSED.value
    with pytest.raises(ValueError):
        store.mark_executed(proposal.id)
    store.approve(proposal.id)
    store.mark_executed(proposal.id)
    assert store.verify(proposal.id).status == ActionStatus.VERIFIED.value


def test_prohibited_actions_are_never_proposed(tmp_path: Path) -> None:
    store = ActionStore(tmp_path / "actions.json")
    for kind in (ActionType.SCHOOL_SUBMISSION, ActionType.SCHOOL_MESSAGE, ActionType.PAYMENT, ActionType.AUTHENTICATION):
        with pytest.raises(PermissionError):
            store.propose(action_type=kind, title="Forbidden")


def test_approval_workflow_links_review_to_exact_action_and_resolves_after_verification(tmp_path: Path) -> None:
    actions = ActionStore(tmp_path / "actions.json")
    reviews = ReviewQueue(tmp_path / "review.json")
    activity = ActivityLog(tmp_path / "activity.jsonl")
    workflow = ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity)

    proposal, review = workflow.propose(
        action_type=ActionType.CALENDAR_CHANGE,
        title="Add midterm",
        details={"date": "2026-10-21"},
    )
    assert review.action_proposal_id == proposal.id
    assert review.status is ReviewStatus.OPEN

    approved_review = workflow.approve_review(review.id)
    assert approved_review.status is ReviewStatus.APPROVED
    assert actions.get(proposal.id).status == ActionStatus.APPROVED.value

    verified = workflow.execute_approved(proposal.id, lambda item: {"verified": True, "id": item.id})
    assert verified.status == ActionStatus.VERIFIED.value
    assert reviews.get(review.id).status is ReviewStatus.RESOLVED
    assert activity.list(limit=1)[0].event_type == "action.verified"


def test_invalid_review_decision_fails_closed_without_state_or_activity(tmp_path: Path) -> None:
    actions = ActionStore(tmp_path / "actions.json")
    reviews = ReviewQueue(tmp_path / "review.json")
    activity = ActivityLog(tmp_path / "activity.jsonl")
    proposal = actions.propose(action_type=ActionType.DOMAIN_CHANGE, title="Update deadline", details={"before": "October 8", "after": "October 11"})
    item = reviews.add(
        kind="deadline_conflict",
        title="Assignment 2 deadline",
        details={"current": "October 8", "new": "October 11"},
        action_proposal_id=proposal.id,
    )

    with pytest.raises(ValueError, match="unsupported review decision"):
        ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity).decide_review(item.id, "banana")

    unchanged = reviews.get(item.id)
    assert unchanged.status is ReviewStatus.OPEN
    assert unchanged.details == {"current": "October 8", "new": "October 11"}
    assert actions.get(proposal.id).status == ActionStatus.PROPOSED.value
    assert activity.list() == []


def test_choose_course_decision_requires_a_recognized_course(tmp_path: Path) -> None:
    actions = ActionStore(tmp_path / "actions.json")
    reviews = ReviewQueue(tmp_path / "review.json")
    activity = ActivityLog(tmp_path / "activity.jsonl")
    courses = [{"id": "POL 2103 - Politics", "code": "POL 2103", "name": "POL 2103 - Politics"}]
    workflow = ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity, courses=courses)
    valid = reviews.add(kind="course_identity_uncertainty", title="Choose course", details={"candidates": [{"id": "POL 2103 - Politics"}]})

    decided = workflow.decide_review(valid.id, "choose_course:POL 2103 - Politics")

    assert decided.status is ReviewStatus.APPROVED
    assert decided.details["decision"] == "choose_course:POL 2103 - Politics"
    assert len(activity.list()) == 1

    invalid = reviews.add(kind="course_identity_uncertainty", title="Choose course", details={"candidates": [{"id": "POL 2103 - Politics"}]})
    activity_count = len(activity.list())
    with pytest.raises(ValueError, match="recognized course"):
        workflow.decide_review(invalid.id, "choose_course:banana")
    assert reviews.get(invalid.id).status is ReviewStatus.OPEN
    assert "decision" not in reviews.get(invalid.id).details
    assert len(activity.list()) == activity_count
