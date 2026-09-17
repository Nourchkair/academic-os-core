from pathlib import Path

import pytest

from academia_os.actions import ActionStatus, ActionStore, ActionType


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
