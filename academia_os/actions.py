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
        items = self._all(); items.append(proposal); self._write(items); return proposal

    def list(self, *, status: str | None = None) -> list[ActionProposal]:
        items = self._all()
        return [item for item in items if status is None or item.status == status]

    def _transition(self, proposal_id: str, status: ActionStatus, *, reason: str | None = None) -> ActionProposal:
        items = self._all()
        for item in items:
            if item.id == proposal_id:
                item.status = status.value; item.updated_at = datetime.now(timezone.utc).isoformat(); item.failure_reason = reason; self._write(items); return item
        raise KeyError(proposal_id)

    def approve(self, proposal_id: str) -> ActionProposal:
        item = next(item for item in self._all() if item.id == proposal_id)
        if item.status != ActionStatus.PROPOSED.value: raise ValueError(f"proposal is not awaiting approval: {item.status}")
        return self._transition(proposal_id, ActionStatus.APPROVED)

    def reject(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.REJECTED)

    def mark_executed(self, proposal_id: str) -> ActionProposal:
        item = next(item for item in self._all() if item.id == proposal_id)
        if item.status != ActionStatus.APPROVED.value: raise ValueError("only approved actions can be executed")
        return self._transition(proposal_id, ActionStatus.EXECUTED)

    def verify(self, proposal_id: str) -> ActionProposal:
        item = next(item for item in self._all() if item.id == proposal_id)
        if item.status != ActionStatus.EXECUTED.value: raise ValueError("only executed actions can be verified")
        return self._transition(proposal_id, ActionStatus.VERIFIED)

    def fail(self, proposal_id: str, reason: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.FAILED, reason=reason)
