from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state import JsonStateStore


class ActionType(StrEnum):
    FILE_COPY = "file_copy"
    FILE_MOVE = "file_move"
    CALENDAR_CHANGE = "calendar_change"
    CONFIGURATION_CHANGE = "configuration_change"
    SCHOOL_SUBMISSION = "school_submission"
    SCHOOL_MESSAGE = "school_message"
    PAYMENT = "payment"
    AUTHENTICATION = "authentication"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    VERIFIED = "verified"
    FAILED = "failed"


PROHIBITED_ACTIONS = {ActionType.SCHOOL_SUBMISSION, ActionType.SCHOOL_MESSAGE, ActionType.PAYMENT, ActionType.AUTHENTICATION}


@dataclass
class ActionProposal:
    id: str
    action_type: str
    title: str
    details: dict[str, Any]
    status: str
    requires_approval: bool
    created_at: str
    updated_at: str
    failure_reason: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionProposal":
        return cls(**value)


class ActionStore:
    def __init__(self, path: Path):
        self.store = JsonStateStore(path)

    def _all(self) -> list[ActionProposal]:
        return [ActionProposal.from_dict(value) for value in self.store.read([])]

    def _write(self, items: list[ActionProposal]) -> None:
        self.store.write([asdict(item) for item in items])

    def propose(self, *, action_type: ActionType | str, title: str, details: dict[str, Any] | None = None, requires_approval: bool = True) -> ActionProposal:
        normalized = ActionType(action_type)
        if normalized in PROHIBITED_ACTIONS:
            raise PermissionError(f"Academia OS never performs {normalized.value} actions")
        now = datetime.now(timezone.utc).isoformat()
        proposal = ActionProposal(str(uuid4()), normalized.value, title, details or {}, ActionStatus.PROPOSED.value, requires_approval, now, now)
        self.store.update([], lambda raw: [*raw, asdict(proposal)])
        return proposal

    def list(self, *, status: str | None = None) -> list[ActionProposal]:
        items = self._all()
        return [item for item in items if status is None or item.status == status]

    def get(self, proposal_id: str) -> ActionProposal:
        for item in self._all():
            if item.id == proposal_id:
                return item
        raise KeyError(f"action proposal not found: {proposal_id}")

    def delete(self, proposal_id: str) -> None:
        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ActionProposal.from_dict(value) for value in raw]
            proposal = next((item for item in items if item.id == proposal_id), None)
            if proposal is None:
                raise KeyError(f"action proposal not found: {proposal_id}")
            if proposal.status != ActionStatus.PROPOSED.value:
                raise ValueError("only unlinked proposed actions can be deleted")
            return [asdict(item) for item in items if item.id != proposal_id]

        self.store.update([], transition)

    def reopen(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.PROPOSED, expected=ActionStatus.APPROVED)

    def _transition(self, proposal_id: str, status: ActionStatus, *, reason: str | None = None, expected: ActionStatus | None = None) -> ActionProposal:
        selected: list[ActionProposal] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ActionProposal.from_dict(value) for value in raw]
            for index, item in enumerate(items):
                if item.id != proposal_id:
                    continue
                if expected is not None and item.status != expected.value:
                    raise ValueError(f"proposal is not {expected.value}: {item.status}")
                item.status = status.value
                item.updated_at = datetime.now(timezone.utc).isoformat()
                item.failure_reason = reason
                items[index] = item
                selected.append(item)
                return [asdict(value) for value in items]
            raise KeyError(proposal_id)

        self.store.update([], transition)
        return selected[0]

    def approve(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.APPROVED, expected=ActionStatus.PROPOSED)

    def reject(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.REJECTED, expected=ActionStatus.PROPOSED)

    def mark_executed(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.EXECUTED, expected=ActionStatus.APPROVED)

    def verify(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.VERIFIED, expected=ActionStatus.EXECUTED)

    def fail(self, proposal_id: str, reason: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.FAILED, reason=reason)
