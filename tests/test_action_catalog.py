from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.action_catalog import (
    ActionContext,
    ActionFrameworkError,
    ActionTier,
    execute_action,
    list_trash,
    preview,
    tier_for,
)
from academia_os.actions import ActionProposal, ActionStatus


def workspace(tmp_path: Path) -> tuple[ActionContext, Path]:
    root = tmp_path / "University"
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "04_READINGS").mkdir(parents=True)
    (course / "04_READINGS" / "week1.md").write_text("reading notes", encoding="utf-8")
    (root / ".academia").mkdir(parents=True)
    return ActionContext(workspace_root=root, state_root=root / ".academia", semester="Fall 2026"), course


def proposal(action_type: str, details: dict, *, proposal_id: str = "proposal-1") -> ActionProposal:
    return ActionProposal(proposal_id, action_type, "test action", details, ActionStatus.APPROVED.value, True, "2026-11-13T00:00:00+00:00", "2026-11-13T00:00:00+00:00")


def test_tiers_follow_the_approved_split() -> None:
    assert tier_for("task_change") is ActionTier.INLINE
    assert tier_for("file_copy") is ActionTier.INLINE
    assert tier_for("grade_record") is ActionTier.INLINE
    assert tier_for("file_restore") is ActionTier.INLINE
    assert tier_for("file_move") is ActionTier.REVIEW
    assert tier_for("file_trash") is ActionTier.REVIEW
    assert tier_for("configuration_change") is ActionTier.REVIEW
    assert tier_for("something_unknown") is ActionTier.REVIEW


def test_preview_names_the_exact_change(tmp_path: Path) -> None:
    context, course = workspace(tmp_path)
    source = f"{course.relative_to(context.root).as_posix()}/04_READINGS/week1.md"

    moved = preview("file_move", {"source": source, "destination": source.replace("week1", "week2")}, context)
    assert moved["tier"] == "review"
    assert moved["changes"][0]["from"] == source
    assert moved["changes"][1]["to"].endswith("week2.md")

    trashed = preview("file_trash", {"path": source}, context)
    assert "recoverable" in trashed["summary"]


def test_preview_rejects_paths_outside_the_workspace(tmp_path: Path) -> None:
    context, _ = workspace(tmp_path)
    with pytest.raises(ActionFrameworkError):
        preview("file_trash", {"path": "../../etc/passwd"}, context)


def test_trash_then_restore_round_trip(tmp_path: Path) -> None:
    context, course = workspace(tmp_path)
    original = course / "04_READINGS" / "week1.md"
    relative = original.relative_to(context.root).as_posix()

    result = execute_action(proposal("file_trash", {"path": relative}), context)
    assert result["verified"] is True
    assert result["restorable"] is True
    assert not original.exists()
    assert list_trash(context)[0]["original"] == relative
    assert (context.trash_root / result["trash_id"]).is_dir()

    restored = execute_action(proposal("file_restore", {"trash_id": result["trash_id"]}, proposal_id="proposal-2"), context)
    assert restored["verified"] is True
    assert original.read_text(encoding="utf-8") == "reading notes"
    assert list_trash(context) == []

    with pytest.raises(ActionFrameworkError, match="already restored"):
        execute_action(proposal("file_restore", {"trash_id": result["trash_id"]}, proposal_id="proposal-3"), context)


def test_move_verifies_destination_and_refuses_collisions(tmp_path: Path) -> None:
    context, course = workspace(tmp_path)
    readings = course / "04_READINGS"
    source = readings / "week1.md"
    destination = readings / "week2.md"

    result = execute_action(proposal("file_move", {
        "source": source.relative_to(context.root).as_posix(),
        "destination": destination.relative_to(context.root).as_posix(),
    }), context)
    assert result["verified"] is True
    assert destination.read_text(encoding="utf-8") == "reading notes"
    assert not source.exists()

    (readings / "week3.md").write_text("taken", encoding="utf-8")
    with pytest.raises(ActionFrameworkError, match="already exists"):
        execute_action(proposal("file_move", {
            "source": destination.relative_to(context.root).as_posix(),
            "destination": (readings / "week3.md").relative_to(context.root).as_posix(),
        }, proposal_id="proposal-2"), context)

    with pytest.raises(ActionFrameworkError, match="source file no longer exists"):
        execute_action(proposal("file_move", {
            "source": (readings / "missing.md").relative_to(context.root).as_posix(),
            "destination": (readings / "week9.md").relative_to(context.root).as_posix(),
        }, proposal_id="proposal-3"), context)


def test_grade_record_writes_and_reads_back(tmp_path: Path) -> None:
    context, course = workspace(tmp_path)
    result = execute_action(proposal("grade_record", {
        "course_id": course.name,
        "semester": "Fall 2026",
        "values": {"kind": "essay", "title": "First Essay", "status": "graded", "grade": "82%"},
    }), context)
    assert result["verified"] is True
    assert result["grade"] == "82%"
    assert result["status"] == "graded"

    updated = execute_action(proposal("grade_record", {
        "course_id": course.name,
        "semester": "Fall 2026",
        "record_id": result["record_id"],
        "values": {"grade": "88%"},
    }, proposal_id="proposal-2"), context)
    assert updated["grade"] == "88%"


def test_unknown_action_type_is_rejected(tmp_path: Path) -> None:
    context, _ = workspace(tmp_path)
    with pytest.raises(ActionFrameworkError, match="no executor"):
        execute_action(proposal("domain_change", {}), context)


def test_workflow_executes_and_verifies_a_trash_through_review(tmp_path: Path) -> None:
    from academia_os.actions import ActionStore, ActionType
    from academia_os.activity import ActivityLog
    from academia_os.review import ReviewQueue
    from academia_os.workflow import ApprovalWorkflow

    context, course = workspace(tmp_path)
    file = course / "04_READINGS" / "week1.md"
    relative = file.relative_to(context.root).as_posix()

    workflow = ApprovalWorkflow(
        actions=ActionStore(context.state / "actions.json"),
        reviews=ReviewQueue(context.state / "review.json"),
        activity=ActivityLog(context.state / "activity.jsonl"),
        courses=[],
    )
    item, review = workflow.propose(
        action_type=ActionType.FILE_TRASH,
        title=f"Trash {relative}",
        details={"proposal": {"path": relative}},
    )
    workflow.approve_review(review.id)
    executed = workflow.execute_approved(
        item.id,
        lambda value: execute_action(value, context, actor="user"),
        actor="user",
    )

    assert executed.status == "verified"
    assert executed.details["operation"]["phase"] == "verified"
    resolved = workflow.reviews.get(review.id)
    assert resolved.details["verification"]["verified"] is True
    assert resolved.details["verification"]["restorable"] is True
    assert not file.exists()
    events = [event.event_type for event in workflow.activity.list(limit=20)]
    assert "action.verified" in events
    verified_event = next(event for event in workflow.activity.list(limit=20) if event.event_type == "action.verified")
    assert verified_event.details["verification"]["trash_id"]
