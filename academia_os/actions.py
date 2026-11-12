from __future__ import annotations

from dataclasses import asdict, dataclass, fields
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
    DOMAIN_CHANGE = "domain_change"
    TASK_CHANGE = "task_change"
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _operation(details: dict[str, Any]) -> dict[str, Any] | None:
    value = details.get("operation")
    return dict(value) if isinstance(value, dict) else None


def _mark_operation(details: dict[str, Any], phase: str, *, attempts: int | None = None) -> dict[str, Any]:
    updated = dict(details)
    timestamp = _now()
    operation = _operation(updated) or {}
    operation.setdefault("id", str(uuid4()))
    operation.setdefault("created_at", timestamp)
    operation.setdefault("attempts", 0)
    operation["phase"] = phase
    operation["updated_at"] = timestamp
    if attempts is not None:
        operation["attempts"] = attempts
    updated["operation"] = operation
    return updated


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
        known = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in known})


class ActionStore:
    def __init__(self, path: Path):
        self.store = JsonStateStore(path)

    def _all(self) -> list[ActionProposal]:
        return [ActionProposal.from_dict(value) for value in self.store.read_strict([])]

    def _write(self, items: list[ActionProposal]) -> None:
        self.store.write([asdict(item) for item in items])

    def propose(self, *, action_type: ActionType | str, title: str, details: dict[str, Any] | None = None, requires_approval: bool = True) -> ActionProposal:
        normalized = ActionType(action_type)
        if normalized in PROHIBITED_ACTIONS:
            raise PermissionError(f"Academia OS never performs {normalized.value} actions")
        now = _now()
        proposal_details = dict(details or {})
        proposal_details.setdefault("operation", {
            "id": str(uuid4()),
            "phase": ActionStatus.PROPOSED.value,
            "created_at": now,
            "updated_at": now,
            "attempts": 0,
        })
        proposal = ActionProposal(str(uuid4()), normalized.value, title, proposal_details, ActionStatus.PROPOSED.value, requires_approval, now, now)
        self.store.update_strict([], lambda raw: [*raw, asdict(proposal)])
        return proposal

    def list(self, *, status: str | None = None) -> list[ActionProposal]:
        items = self._all()
        return [item for item in items if status is None or item.status == status]

    def amend(self, proposal_id: str, details: dict[str, Any], *, title: str | None = None) -> ActionProposal:
        """Replace the details of one still-unapproved proposal."""
        selected: list[ActionProposal] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ActionProposal.from_dict(value) for value in raw]
            for index, item in enumerate(items):
                if item.id != proposal_id:
                    continue
                if item.status != ActionStatus.PROPOSED.value:
                    raise ValueError(f"proposal is not proposed: {item.status}")
                item.details = dict(details)
                if title is not None:
                    item.title = title
                item.updated_at = _now()
                item.failure_reason = None
                items[index] = item
                selected.append(item)
                return [asdict(value) for value in items]
            raise KeyError(proposal_id)

        self.store.update_strict([], transition)
        return selected[0]

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

        self.store.update_strict([], transition)

    def reopen(self, proposal_id: str) -> ActionProposal:
        return self._transition(proposal_id, ActionStatus.PROPOSED, expected=ActionStatus.APPROVED)

    def _transition(
        self,
        proposal_id: str,
        status: ActionStatus,
        *,
        reason: str | None = None,
        expected: ActionStatus | None = None,
        operation_phase: str | None = None,
    ) -> ActionProposal:
        selected: list[ActionProposal] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ActionProposal.from_dict(value) for value in raw]
            for index, item in enumerate(items):
                if item.id != proposal_id:
                    continue
                if expected is not None and item.status != expected.value:
                    raise ValueError(f"proposal is not {expected.value}: {item.status}")
                item.status = status.value
                item.updated_at = _now()
                item.failure_reason = reason
                if operation_phase is not None:
                    item.details = _mark_operation(item.details, operation_phase)
                items[index] = item
                selected.append(item)
                return [asdict(value) for value in items]
            raise KeyError(proposal_id)

        self.store.update_strict([], transition)
        return selected[0]

    def approve(self, proposal_id: str) -> ActionProposal:
        return self._transition(
            proposal_id,
            ActionStatus.APPROVED,
            expected=ActionStatus.PROPOSED,
            operation_phase=ActionStatus.APPROVED.value,
        )

    def reject(self, proposal_id: str) -> ActionProposal:
        return self._transition(
            proposal_id,
            ActionStatus.REJECTED,
            expected=ActionStatus.PROPOSED,
            operation_phase=ActionStatus.REJECTED.value,
        )

    def begin_execution(self, proposal_id: str, *, recovery: bool = False) -> ActionProposal:
        """Start or resume one execution attempt without duplicating completion."""
        selected: list[ActionProposal] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = [ActionProposal.from_dict(value) for value in raw]
            for index, item in enumerate(items):
                if item.id != proposal_id:
                    continue
                operation = _operation(item.details) or {}
                if recovery:
                    if item.status != ActionStatus.EXECUTED.value or operation.get("phase") != "executing":
                        raise ValueError("proposal is not a recoverable interrupted execution")
                elif item.status != ActionStatus.APPROVED.value:
                    raise ValueError(f"proposal is not approved: {item.status}")
                if not operation:
                    # Legacy approved records predate operation metadata. Backfill
                    # one deterministic operation before their first execution.
                    operation = {
                        "id": str(uuid4()),
                        "phase": ActionStatus.APPROVED.value,
                        "created_at": item.updated_at,
                        "updated_at": item.updated_at,
                        "attempts": 0,
                    }
                    item.details["operation"] = operation
                item.status = ActionStatus.EXECUTED.value
                item.updated_at = _now()
                item.failure_reason = None
                item.details = _mark_operation(
                    item.details,
                    "executing",
                    attempts=int(operation.get("attempts", 0)) + 1,
                )
                operation = _operation(item.details) or {}
                operation["started_at"] = item.updated_at
                item.details["operation"] = operation
                items[index] = item
                selected.append(item)
                return [asdict(value) for value in items]
            raise KeyError(proposal_id)

        self.store.update_strict([], transition)
        return selected[0]

    def mark_executed(self, proposal_id: str) -> ActionProposal:
        return self.begin_execution(proposal_id)

    def verify(self, proposal_id: str) -> ActionProposal:
        return self._transition(
            proposal_id,
            ActionStatus.VERIFIED,
            expected=ActionStatus.EXECUTED,
            operation_phase=ActionStatus.VERIFIED.value,
        )

    def fail(self, proposal_id: str, reason: str) -> ActionProposal:
        return self._transition(
            proposal_id,
            ActionStatus.FAILED,
            reason=reason,
            operation_phase=ActionStatus.FAILED.value,
        )
