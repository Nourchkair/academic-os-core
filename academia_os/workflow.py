from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .actions import ActionProposal, ActionStatus, ActionStore, ActionType
from .activity import ActivityLog
from .review import ReviewItem, ReviewQueue, ReviewStatus


def is_review_rejection_decision(decision: str) -> bool:
    normalized = decision.strip()
    return normalized in {"reject", "dismiss", "keep_current", "keep_existing", "keep_unassigned", "keep_general_intake"} or normalized.startswith("reject_") or normalized.startswith("dismiss_")


class ApprovalWorkflow:
    """Coordinate action proposals, human review, verification, and activity.

    The core never performs external side effects itself. ``execute_approved``
    receives an explicit executor for the already-approved proposal and only
    resolves the linked Review item after that executor returns verification
    data successfully.
    """

    def __init__(self, *, actions: ActionStore, reviews: ReviewQueue, activity: ActivityLog) -> None:
        self.actions = actions
        self.reviews = reviews
        self.activity = activity

    def propose(
        self,
        *,
        action_type: ActionType | str,
        title: str,
        details: dict[str, Any] | None = None,
        course: str | None = None,
        priority: str = "normal",
        review_kind: str = "action_approval",
        review_details: dict[str, Any] | None = None,
    ) -> tuple[ActionProposal, ReviewItem]:
        proposal = self.actions.propose(action_type=action_type, title=title, details=details)
        try:
            review = self.reviews.add(
                kind=review_kind,
                title=title,
                course=course,
                priority=priority,
                action_proposal_id=proposal.id,
                details={
                    "action_type": proposal.action_type,
                    "proposal_details": dict(proposal.details),
                    **(review_details or {}),
                },
            )
        except Exception:
            self.actions.delete(proposal.id)
            raise
        self.activity.append(
            event_type="action.proposed",
            title=title,
            course=course,
            details={"proposal_id": proposal.id, "review_id": review.id, "action_type": proposal.action_type},
            actor="system",
        )
        return proposal, review

    def approve_review(self, review_id: str) -> ReviewItem:
        review = self.reviews.get(review_id)
        if review.action_proposal_id:
            proposal = self.actions.approve(review.action_proposal_id)
            try:
                updated = self.reviews.update(
                    review.id,
                    status=ReviewStatus.APPROVED,
                    details=self._with_details(review, {"action_status": proposal.status}),
                )
            except Exception:
                self.actions.reopen(review.action_proposal_id)
                raise
            self.activity.append(
                event_type="action.approved",
                title=review.title,
                course=review.course,
                details={"proposal_id": proposal.id, "review_id": review.id},
                actor="user",
            )
            return updated
        return self.reviews.update(review_id, status=ReviewStatus.APPROVED)

    def reject_review(self, review_id: str) -> ReviewItem:
        review = self.reviews.get(review_id)
        if review.action_proposal_id:
            proposal = self.actions.reject(review.action_proposal_id)
            updated = self.reviews.update(
                review.id,
                status=ReviewStatus.REJECTED,
                details=self._with_details(review, {"action_status": proposal.status}),
            )
            self.activity.append(
                event_type="action.rejected",
                title=review.title,
                course=review.course,
                details={"proposal_id": proposal.id, "review_id": review.id},
                actor="user",
            )
            return updated
        return self.reviews.update(review_id, status=ReviewStatus.REJECTED)

    def decide_review(self, review_id: str, decision: str) -> ReviewItem:
        decision = decision.strip()
        if not decision:
            raise ValueError("review decision is required")
        review = self.reviews.get(review_id)
        rejection = is_review_rejection_decision(decision)
        status = ReviewStatus.REJECTED if rejection else ReviewStatus.APPROVED
        action_status: str | None = None
        if review.action_proposal_id:
            proposal = self.actions.reject(review.action_proposal_id) if rejection else self.actions.approve(review.action_proposal_id)
            action_status = proposal.status
        details = self._with_details(review, {"decision": decision, "decision_at": datetime.now(timezone.utc).isoformat()})
        if action_status is not None:
            details["action_status"] = action_status
        updated = self.reviews.update(review_id, status=status, details=details)
        self.activity.append(
            event_type="review.decided",
            title=review.title,
            course=review.course,
            details={"review_id": review_id, "decision": decision, "status": status.value, "action_status": action_status},
            actor="user",
        )
        return updated

    def resolve_review(self, review_id: str) -> ReviewItem:
        review = self.reviews.get(review_id)
        if review.action_proposal_id:
            proposal = self.actions.get(review.action_proposal_id)
            if proposal.status != ActionStatus.VERIFIED.value:
                raise ValueError("action-linked review items resolve only after proposal verification")
        return self.reviews.update(review_id, status=ReviewStatus.RESOLVED)

    def execute_approved(self, proposal_id: str, executor: Callable[[ActionProposal], dict[str, Any]]) -> ActionProposal:
        proposal = self.actions.get(proposal_id)
        if proposal.status != ActionStatus.APPROVED.value:
            raise ValueError(f"proposal is not approved: {proposal.status}")
        self.actions.mark_executed(proposal_id)
        try:
            verification = executor(proposal)
            if not isinstance(verification, dict):
                raise TypeError("action executor must return a JSON object")
            verified = self.actions.verify(proposal_id)
        except Exception as exc:
            failed = self.actions.fail(proposal_id, str(exc))
            review = self.reviews.find_by_action_proposal_id(proposal_id)
            if review:
                self.reviews.update(
                    review.id,
                    status=ReviewStatus.OPEN,
                    details=self._with_details(review, {"action_status": failed.status, "failure_reason": str(exc)}),
                )
            self.activity.append(
                event_type="action.failed",
                title=proposal.title,
                details={"proposal_id": proposal_id, "failure_reason": str(exc)},
                actor="system",
            )
            raise

        review = self.reviews.find_by_action_proposal_id(proposal_id)
        if review:
            self.reviews.update(
                review.id,
                status=ReviewStatus.RESOLVED,
                details=self._with_details(review, {"action_status": verified.status, "verification": verification}),
            )
        self.activity.append(
            event_type="action.verified",
            title=proposal.title,
            details={"proposal_id": proposal_id, "verification": verification},
            actor="system",
        )
        return verified

    @staticmethod
    def _with_details(review: ReviewItem, additions: dict[str, Any]) -> dict[str, Any]:
        details = dict(review.details)
        details.update(additions)
        return details
