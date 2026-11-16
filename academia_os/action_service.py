"""Propose, preview, and execute workspace actions for the agent page.

This is the service the HTTP API and (later) the model tools share. It keeps
three rules in one place: an action is validated and previewed before it is
stored, a ``review`` action can never run through the inline shortcut, and an
inline action still records its own execution and verification in Activity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .action_catalog import ActionContext, ActionFrameworkError, ActionTier, execute_action, preview, tier_for
from .actions import ActionProposal, ActionStatus, ActionStore, ActionType
from .activity import ActivityLog
from .config import load_config, runtime_directory
from .review import ReviewQueue
from .workflow import ApprovalWorkflow


class ActionService:
    def __init__(self, profile_path: Path | None = None, *, config: dict[str, Any] | None = None) -> None:
        if config is None and profile_path is None:
            raise ValueError("an action service needs a profile path or a loaded config")
        self.profile_path = Path(profile_path).expanduser().resolve() if profile_path is not None else None
        self.config = config if config is not None else load_config(self.profile_path)
        self.root = Path(str(self.config["academic"]["root_directory"])).expanduser().resolve()
        self.state = runtime_directory(self.config)
        self.actions = ActionStore(self.state / "actions.json")
        self.activity = ActivityLog(self.state / "activity.jsonl")
        self.workflow = ApprovalWorkflow(
            actions=self.actions,
            reviews=ReviewQueue(self.state / "review.json"),
            activity=self.activity,
            courses=[],
        )

    def context(self) -> ActionContext:
        return ActionContext(
            workspace_root=self.root,
            state_root=self.state,
            semester=str(self.config["academic"]["semester"]),
            profile_path=self.profile_path,
        )

    def propose(self, action_type: str, details: Mapping[str, Any], *, title: str | None = None) -> dict[str, Any]:
        normalized = ActionType(str(action_type))
        if normalized.value not in {item.value for item in ActionType}:
            raise ActionFrameworkError("unknown action type")
        context = self.context()
        described = preview(normalized.value, details, context)
        tier = tier_for(normalized)
        payload = {"proposal": dict(details), "preview": described}
        review_id = None
        if tier is ActionTier.REVIEW:
            # Review-tier actions get a linked Review item so the student has one
            # place to approve, execute, and read the verification record.
            proposal, review = self.workflow.propose(
                action_type=normalized,
                title=(title or described["title"])[:200],
                details=payload,
            )
            review_id = review.id
        else:
            proposal = self.actions.propose(
                action_type=normalized,
                title=(title or described["title"])[:200],
                details=payload,
                requires_approval=True,
            )
            self.activity.append(
                event_type="action.proposed",
                title=proposal.title,
                details={"proposal_id": proposal.id, "action_type": normalized.value, "tier": tier.value},
                actor="agent",
            )
        return {
            "proposal_id": proposal.id,
            "action_type": normalized.value,
            "tier": tier.value,
            "requires_review": tier is ActionTier.REVIEW,
            "review_id": review_id,
            "preview": described,
            "status": proposal.status,
        }

    def execute_inline(self, proposal_id: str, *, actor: str = "user") -> dict[str, Any]:
        proposal = self.actions.get(proposal_id)
        tier = tier_for(proposal.action_type)
        if tier is ActionTier.REVIEW:
            raise PermissionError("this action needs a Review decision before it can run")
        if proposal.status != ActionStatus.PROPOSED.value:
            raise ValueError(f"action is not pending: {proposal.status}")
        # The student pressing Allow is the approval decision for this tier.
        self.actions.approve(proposal.id)
        self.activity.append(
            event_type="action.approved",
            title=proposal.title,
            details={"proposal_id": proposal.id, "tier": tier.value},
            actor=actor,
        )
        executing = self.actions.begin_execution(proposal.id)
        operation = executing.details.get("operation") if isinstance(executing.details.get("operation"), dict) else {}
        try:
            verification = execute_action(executing, self.context(), actor=actor)
            if not isinstance(verification, dict):
                raise ActionFrameworkError("the action did not return a verification record")
            verified = self.actions.verify(proposal.id)
        except Exception as exc:
            failed = self.actions.fail(proposal.id, str(exc))
            self.activity.append(
                event_type="action.failed",
                title=proposal.title,
                details={"proposal_id": proposal.id, "tier": tier.value, "failure_reason": str(exc)},
                actor=actor,
            )
            raise ActionFrameworkError(f"{failed.status}: {exc}") from exc
        self.activity.append(
            event_type="action.executed",
            title=proposal.title,
            details={"proposal_id": proposal.id, "tier": tier.value, "operation_id": operation.get("id")},
            actor=actor,
        )
        self.activity.append(
            event_type="action.verified",
            title=proposal.title,
            details={"proposal_id": proposal.id, "operation_id": operation.get("id"), "verification": verification},
            actor=actor,
        )
        return {
            "proposal_id": proposal.id,
            "action_type": proposal.action_type,
            "status": verified.status,
            "tier": tier.value,
            "verification": verification,
        }

    def discard(self, proposal_id: str, *, actor: str = "user") -> dict[str, Any]:
        proposal = self.actions.get(proposal_id)
        if proposal.status != ActionStatus.PROPOSED.value:
            raise ValueError(f"only pending actions can be discarded: {proposal.status}")
        self.actions.delete(proposal_id)
        self.activity.append(
            event_type="action.discarded",
            title=proposal.title,
            details={"proposal_id": proposal.id, "action_type": proposal.action_type},
            actor=actor,
        )
        return {"proposal_id": proposal.id, "discarded": True}

    def pending(self) -> list[dict[str, Any]]:
        items: list[ActionProposal] = self.actions.list(status=ActionStatus.PROPOSED.value)
        return [
            {
                "proposal_id": item.id,
                "review_id": (review.id if (review := self.workflow.reviews.find_by_action_proposal_id(item.id)) else None),
                "action_type": item.action_type,
                "title": item.title,
                "tier": tier_for(item.action_type).value,
                "preview": item.details.get("preview") if isinstance(item.details.get("preview"), dict) else None,
                "created_at": item.created_at,
            }
            for item in items
        ]
