"""Durable local ChangeSet execution, recovery, and conditional reversal."""
from __future__ import annotations

from typing import Any

from ..assignment_history import list_assignment_history
from .model import (
    DEFAULT_MAX_ATTEMPTS,
    ChangeSet,
    Operation,
    approval_hash,
    derive_changeset_status,
    now,
)
from .service import KnowledgeService


class OperationConflict(RuntimeError):
    """The target changed after the proposal; do not overwrite it."""


class ChangeExecutor:
    def __init__(self, service: KnowledgeService) -> None:
        self.service = service
        self.store = service.store

    # Public entry points

    def execute(self, changeset_id: str, *, actor: str, channel: str, retry: bool = False) -> dict[str, Any]:
        with self.store.execution_lock():
            changeset = ChangeSet.from_dict(self.store.get_changeset(changeset_id))
            if changeset.status == "cancelled":
                raise ValueError("a cancelled changeset cannot be executed")
            if changeset.status == "proposed":
                raise PermissionError("the changeset has not been approved")
            if changeset.status in {"reverted", "partially_reverted", "reversal_conflict"}:
                raise ValueError(f"a changeset in {changeset.status} cannot be executed")
            self._validate_approval(changeset)
            if changeset.status == "verified" and not retry:
                return self.service.get_changeset(changeset.id)
            self._recover_changeset(changeset)
            changeset = ChangeSet.from_dict(self.store.get_changeset(changeset_id))
            self._validate_approval(changeset)
            changeset.status = "executing"
            changeset.updated_at = now()
            changeset.execution["started_at"] = changeset.execution.get("started_at") or now()
            changeset.execution["last_actor"] = actor
            changeset.execution["attempts"] = int(changeset.execution.get("attempts") or 0) + 1
            self.store.save_changeset(changeset)
            self.store.append_event(changeset_id=changeset.id, event_type="changeset.execution_started", actor=actor, channel=channel)
            for operation in _topological(changeset):
                if operation.status in {"verified", "skipped", "reversed", "already_reversed"}:
                    continue
                if operation.status == "conflict":
                    continue
                if operation.id not in set(changeset.approval.get("approved_operation_ids", [])):
                    if operation.required:
                        raise PermissionError(f"required operation was not approved: {operation.id}")
                    if operation.status != "skipped":
                        self._mark_skipped(changeset, operation, actor=actor, channel=channel)
                    continue
                dependencies = [next(item for item in changeset.operations if item.id == dependency) for dependency in operation.depends_on]
                if any(dependency.status != "verified" for dependency in dependencies):
                    self._mark_blocked(changeset, operation, actor=actor, channel=channel)
                    continue
                if operation.attempts >= DEFAULT_MAX_ATTEMPTS and operation.status in {"failed", "blocked"}:
                    operation.status = "failed"
                    operation.last_error = "retry limit reached"
                    self.store.save_changeset(changeset)
                    continue
                self._execute_operation(changeset, operation, actor=actor, channel=channel)
            self._finalize(changeset, actor=actor, channel=channel)
            return self.service.get_changeset(changeset.id)

    def recover(self) -> dict[str, Any]:
        recovered: list[str] = []
        with self.store.execution_lock():
            for raw in self.store.list_changesets():
                if raw.get("status") not in {"executing", "approved", "partially_applied", "failed"}:
                    continue
                changeset = ChangeSet.from_dict(raw)
                if not any(operation.status == "executing" for operation in changeset.operations):
                    continue
                self._recover_changeset(changeset)
                recovered.append(changeset.id)
        if recovered:
            self.service._activity().append(
                event_type="knowledge.change.recovered",
                title=f"Recovered {len(recovered)} interrupted academic change{'s' if len(recovered) != 1 else ''}",
                source=f"{self.service.semester}/.academia/knowledge/change_journal.json",
                confidence="unverified",
                actor="system",
                details={"changesets": recovered},
            )
        return {"recovered_changesets": len(recovered), "changesets": recovered}

    def reverse(self, changeset_id: str, *, actor: str, channel: str) -> dict[str, Any]:
        with self.store.execution_lock():
            changeset = ChangeSet.from_dict(self.store.get_changeset(changeset_id))
            if changeset.reversal.get("status") in {"reverted", "partially_reverted", "reversal_conflict"}:
                return self.service.get_changeset(changeset.id)
            if changeset.status not in {"verified", "partially_applied", "failed"}:
                raise ValueError(f"changeset cannot be reversed from {changeset.status}")
            if not any(operation.status == "verified" for operation in changeset.operations):
                raise ValueError("no verified operations can be reversed")
            changeset.reversal = {
                "status": "in_progress",
                "requested_at": now(),
                "approved_by": actor,
                "completed_at": None,
                "operation_results": [],
            }
            changeset.updated_at = now()
            self.store.save_changeset(changeset)
            self.store.append_event(changeset_id=changeset.id, event_type="changeset.reversal_requested", actor=actor, channel=channel)
            conflicts = False
            reversed_any = False
            irreversible_any = False
            for operation in reversed(_topological(changeset)):
                if operation.status not in {"verified", "already_reversed"}:
                    continue
                if not operation.reversible:
                    irreversible_any = True
                    changeset.reversal["operation_results"].append({
                        "operation_id": operation.id,
                        "status": "irreversible",
                        "reason": "This operation is marked irreversible.",
                    })
                    continue
                try:
                    current = self._read_target(changeset, operation)
                    if current == operation.before:
                        operation.status = "already_reversed"
                        changeset.reversal["operation_results"].append({"operation_id": operation.id, "status": "already_reversed"})
                        reversed_any = True
                        continue
                    if current != operation.after:
                        raise OperationConflict("the target changed after the approved operation")
                    self._reverse_operation(changeset, operation, actor=actor)
                    if self._read_target(changeset, operation) != operation.before:
                        raise ValueError("reversal readback did not match the previous value")
                    if operation.type == "assessment.set_deadline":
                        self.service.record_reversal_assertion(operation, changeset_id=changeset.id)
                    operation.status = "reversed"
                    operation.completed_at = now()
                    changeset.reversal["operation_results"].append({"operation_id": operation.id, "status": "reversed", "value": operation.before})
                    reversed_any = True
                    self.store.append_event(
                        changeset_id=changeset.id,
                        event_type="operation.reversed",
                        actor=actor,
                        channel=channel,
                        operation_id=operation.id,
                        details={"before": operation.after, "after": operation.before},
                    )
                except OperationConflict as exc:
                    operation.status = "reversal_conflict"
                    operation.last_error = str(exc)
                    conflicts = True
                    changeset.reversal["operation_results"].append({"operation_id": operation.id, "status": "reversal_conflict", "reason": str(exc)})
                    self.store.append_event(
                        changeset_id=changeset.id,
                        event_type="operation.reversal_conflict",
                        actor=actor,
                        channel=channel,
                        operation_id=operation.id,
                        details={"reason": str(exc)},
                    )
                except Exception as exc:  # preserve the original audit and report the exact failure
                    operation.status = "reversal_conflict"
                    operation.last_error = str(exc)
                    conflicts = True
                    changeset.reversal["operation_results"].append({"operation_id": operation.id, "status": "reversal_conflict", "reason": str(exc)})
            if conflicts:
                changeset.reversal["status"] = "reversal_conflict"
                changeset.status = "reversal_conflict"
                event_type = "changeset.reversal_conflict"
                activity_type = "knowledge.change.reversal_conflict"
            elif irreversible_any or any(operation.status in {"failed", "blocked", "conflict"} for operation in changeset.operations):
                changeset.reversal["status"] = "partially_reverted"
                changeset.status = "partially_reverted"
                event_type = "changeset.partially_reverted"
                activity_type = "knowledge.change.reversed"
            elif reversed_any:
                changeset.reversal["status"] = "reverted"
                changeset.status = "reverted"
                event_type = "changeset.reverted"
                activity_type = "knowledge.change.reversed"
            else:
                changeset.reversal["status"] = "partially_reverted"
                changeset.status = "partially_reverted"
                event_type = "changeset.partially_reverted"
                activity_type = "knowledge.change.reversed"
            changeset.reversal["completed_at"] = now()
            changeset.updated_at = now()
            changeset.result["state"] = changeset.status
            changeset.result["operation_results"] = _operation_results(changeset)
            changeset.result["summary"] = _result_summary(changeset)
            self.store.save_changeset(changeset)
            self.store.append_event(changeset_id=changeset.id, event_type=event_type, actor=actor, channel=channel, details={"status": changeset.reversal["status"]})
            self.service._activity().append(
                event_type=activity_type,
                title=f"Change {'reversed' if changeset.reversal['status'] == 'reverted' else 'reversal needs review'}: {changeset.title}",
                course=changeset.course_id,
                source=f"{self.service.semester}/.academia/knowledge/change_journal.json",
                confidence="unverified",
                actor=actor,
                details={"changeset_id": changeset.id, "status": changeset.reversal["status"]},
            )
            return self.service.get_changeset(changeset.id)

    # Validation and recovery

    def _validate_approval(self, changeset: ChangeSet) -> None:
        approval = changeset.approval or {}
        if approval.get("status") != "approved":
            raise PermissionError("the changeset has no student approval")
        if int(approval.get("version") or -1) != int(changeset.version):
            raise PermissionError("the approval belongs to a different changeset version")
        if approval.get("approval_hash") != approval_hash(changeset):
            raise PermissionError("the changeset payload changed after approval")
        approved = set(approval.get("approved_operation_ids", []))
        if not approved:
            raise PermissionError("no operations were approved")

    def _recover_changeset(self, changeset: ChangeSet) -> None:
        changed = False
        for operation in changeset.operations:
            if operation.status != "executing":
                continue
            try:
                current = self._read_target(changeset, operation)
            except Exception as exc:
                operation.status = "conflict"
                operation.last_error = str(exc)
                changed = True
                continue
            if current == operation.after:
                operation.status = "verified"
                operation.result = {"verified": True, "recovered": True, "value": current, "read_at": now()}
                operation.completed_at = now()
                assertion_id = operation.target.get("assertion_id") if operation.type == "assessment.set_deadline" else None
                if assertion_id:
                    self.service.apply_assertion(str(assertion_id), changeset_id=changeset.id)
                if operation.type == "task.set_due":
                    self._update_link_sync(operation, str(operation.after), actor="system")
                changed = True
                self.store.append_event(
                    changeset_id=changeset.id,
                    event_type="operation.verified",
                    actor="system",
                    channel="internal",
                    operation_id=operation.id,
                    details={"recovered": True, "value": current},
                )
            elif current == operation.before:
                operation.status = "approved" if operation.attempts < DEFAULT_MAX_ATTEMPTS else "failed"
                operation.last_error = "recovered before the target write; safe to retry" if operation.status == "approved" else "retry limit reached during recovery"
                changed = True
            else:
                operation.status = "conflict"
                operation.last_error = "the target changed during recovery"
                changed = True
        if not changed:
            return
        changeset.status = derive_changeset_status(changeset)
        changeset.updated_at = now()
        changeset.result["state"] = changeset.status
        changeset.result["operation_results"] = _operation_results(changeset)
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="changeset.recovered",
            actor="system",
            channel="internal",
            details={"status": changeset.status},
        )

    # Operation execution

    def _execute_operation(self, changeset: ChangeSet, operation: Operation, *, actor: str, channel: str) -> None:
        operation.status = "executing"
        operation.attempts = int(operation.attempts or 0) + 1
        operation.started_at = now()
        operation.last_error = None
        operation.error_class = None
        changeset.updated_at = now()
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="operation.executing",
            actor=actor,
            channel=channel,
            operation_id=operation.id,
            details={"attempt": operation.attempts, "before": operation.before, "after": operation.after},
        )
        try:
            already_applied = self._apply_operation(changeset, operation, actor=actor)
            current = self._read_target(changeset, operation)
            if current != operation.after:
                raise ValueError("verification readback did not match the approved value")
            assertion_id = operation.target.get("assertion_id") if operation.type == "assessment.set_deadline" else None
            if assertion_id:
                self.service.apply_assertion(str(assertion_id), changeset_id=changeset.id)
            operation.status = "verified"
            operation.result = {"verified": True, "already_applied": already_applied, "value": current, "read_at": now()}
            operation.completed_at = now()
            self.store.append_event(
                changeset_id=changeset.id,
                event_type="operation.verified",
                actor=actor,
                channel=channel,
                operation_id=operation.id,
                details={"value": current, "already_applied": already_applied},
            )
        except OperationConflict as exc:
            operation.status = "conflict"
            operation.last_error = str(exc)
            operation.error_class = "OperationConflict"
            operation.completed_at = now()
            self.store.append_event(
                changeset_id=changeset.id,
                event_type="operation.conflict",
                actor=actor,
                channel=channel,
                operation_id=operation.id,
                details={"reason": str(exc)},
            )
        except Exception as exc:  # never report a failed write as success
            operation.status = "failed"
            operation.last_error = str(exc)
            operation.error_class = type(exc).__name__
            operation.completed_at = now()
            self.store.append_event(
                changeset_id=changeset.id,
                event_type="operation.failed",
                actor=actor,
                channel=channel,
                operation_id=operation.id,
                details={"reason": str(exc), "error_class": type(exc).__name__},
            )
        changeset.updated_at = now()
        self.store.save_changeset(changeset)

    def _apply_operation(self, changeset: ChangeSet, operation: Operation, *, actor: str) -> bool:
        if operation.type == "assessment.set_deadline":
            owner_kind = str(operation.target.get("owner_kind") or "")
            if owner_kind == "assignment_history":
                current = self._read_target(changeset, operation)
                if current == operation.after:
                    return True
                if current != operation.before:
                    raise OperationConflict("the assessment deadline changed after the proposal")
                record_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                self.service.update_history_deadline(
                    course_id=changeset.course_id,
                    record_id=record_id,
                    before=str(operation.before),
                    after=str(operation.after),
                    actor=actor,
                )
                return False
            if owner_kind == "domain_projection":
                entity_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                domain = self.service.domain()
                try:
                    entity = domain.get("assignment", entity_id)
                except KeyError as exc:
                    raise OperationConflict("the extracted assessment no longer exists") from exc
                current = entity.get("deadline")
                if current == operation.after:
                    return True
                if current != operation.before:
                    raise OperationConflict("the assessment deadline changed after the proposal")
                evidence = self._operation_evidence(operation)
                domain.update_field("assignment", entity_id, "deadline", operation.after, expected_before=operation.before, evidence=evidence)
                return False
            raise OperationConflict("assertion-only assessments cannot be materialized in Phase 1")
        if operation.type == "task.set_due":
            task_store = self.service.task_store()
            try:
                task = task_store.get(str(operation.target["entity_id"]))
            except KeyError as exc:
                raise OperationConflict("the task no longer exists") from exc
            current = task.get("due_date")
            if current == operation.after:
                self._update_link_sync(operation, str(operation.after), actor=actor)
                return True
            if current != operation.before:
                raise OperationConflict("the task deadline changed after the proposal")
            task_store.update_due_date_if_unchanged(
                str(operation.target["entity_id"]),
                before=operation.before,
                after=operation.after,
                actor=actor,
            )
            self._update_link_sync(operation, str(operation.after), actor=actor)
            return False
        raise OperationConflict(f"unsupported operation type: {operation.type}")

    def _reverse_operation(self, changeset: ChangeSet, operation: Operation, *, actor: str) -> None:
        if operation.type == "assessment.set_deadline":
            owner_kind = str(operation.target.get("owner_kind") or "")
            if owner_kind == "assignment_history":
                record_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                self.service.update_history_deadline(
                    course_id=changeset.course_id,
                    record_id=record_id,
                    before=str(operation.after),
                    after=str(operation.before),
                    actor=actor,
                )
                return
            if owner_kind == "domain_projection":
                entity_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                domain = self.service.domain()
                reversal_evidence = {
                    "source": "Reversed approved change",
                    "source_path": "student-report",
                    "provenance": "USER-CREATED",
                    "confidence": "unverified",
                    "authority": "system",
                    "reference": {"changeset_id": changeset.id},
                }
                domain.update_field("assignment", entity_id, "deadline", operation.before, expected_before=operation.after, evidence=reversal_evidence)
                return
            raise OperationConflict("assertion-only assessments cannot be reversed")
        if operation.type == "task.set_due":
            task_store = self.service.task_store()
            task_store.update_due_date_if_unchanged(
                str(operation.target["entity_id"]),
                before=operation.after,
                after=operation.before,
                actor=actor,
            )
            self._update_link_sync(operation, str(operation.before), actor=actor)
            return
        raise OperationConflict(f"unsupported operation type: {operation.type}")

    def _update_link_sync(self, operation: Operation, value: str, *, actor: str) -> None:
        link_id = operation.target.get("link_id")
        if not link_id:
            return
        from .model import TaskLink

        existing = self.store.get_link(str(link_id))
        link = TaskLink.from_dict({
            **existing,
            "last_synced_due_date": value,
            "updated_at": now(),
            "updated_by": actor,
        })
        self.store.upsert_link(link)

    def _read_target(self, changeset: ChangeSet, operation: Operation) -> Any:
        if operation.type == "assessment.set_deadline":
            owner_kind = str(operation.target.get("owner_kind") or "")
            if owner_kind == "assignment_history":
                record_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                for record in list_assignment_history(self.service.root, self.service.semester, changeset.course_id):
                    if str(record.get("id")) == record_id:
                        return record.get("due_date")
                raise OperationConflict("the assessment history record no longer exists")
            if owner_kind == "domain_projection":
                entity_id = str(operation.target["entity_id"]).rsplit(":", 1)[-1]
                try:
                    entity = self.service.domain().get("assignment", entity_id)
                except KeyError as exc:
                    raise OperationConflict("the extracted assessment no longer exists") from exc
                return entity.get("deadline")
            raise OperationConflict("assertion-only assessments have no materialized target")
        if operation.type == "task.set_due":
            try:
                task = self.service.task_store().get(str(operation.target["entity_id"]))
            except KeyError as exc:
                raise OperationConflict("the task no longer exists") from exc
            return task.get("due_date")
        raise OperationConflict(f"unsupported operation type: {operation.type}")

    def _operation_evidence(self, operation: Operation) -> dict[str, Any]:
        evidence_map = self.store.evidence_map()
        for evidence_id in operation.evidence_ids:
            if evidence_id in evidence_map:
                value = dict(evidence_map[evidence_id])
                if not value.get("source_path"):
                    value["source_path"] = "student-report"
                return value
        return {
            "source": "Approved academic change",
            "source_path": "student-report",
            "provenance": "USER-CREATED",
            "confidence": "unverified",
            "authority": "student",
        }

    # Terminal states

    def _mark_skipped(self, changeset: ChangeSet, operation: Operation, *, actor: str, channel: str) -> None:
        operation.status = "skipped"
        operation.completed_at = now()
        operation.result = {"skipped": True, "reason": "not selected for approval"}
        dependencies = [next(item for item in changeset.operations if item.id == dependency) for dependency in operation.depends_on]
        if operation.skip_effect and all(dependency.status == "verified" for dependency in dependencies):
            self.service.apply_skip_effect(changeset.id, operation, actor=actor, channel=channel)
            operation.skip_effect_applied = True
        changeset.updated_at = now()
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="operation.skipped",
            actor=actor,
            channel=channel,
            operation_id=operation.id,
            details={"skip_effect": operation.skip_effect, "effect_applied": operation.skip_effect_applied},
        )

    def _mark_blocked(self, changeset: ChangeSet, operation: Operation, *, actor: str, channel: str) -> None:
        operation.status = "blocked"
        operation.last_error = "a dependency did not verify"
        operation.completed_at = now()
        changeset.updated_at = now()
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="operation.blocked",
            actor=actor,
            channel=channel,
            operation_id=operation.id,
            details={"depends_on": operation.depends_on},
        )

    def _finalize(self, changeset: ChangeSet, *, actor: str, channel: str) -> None:
        changeset.status = derive_changeset_status(changeset)
        changeset.updated_at = now()
        if not any(operation.status == "executing" for operation in changeset.operations):
            changeset.execution["completed_at"] = now()
        changeset.result = {
            "state": changeset.status,
            "operation_results": _operation_results(changeset),
            "summary": _result_summary(changeset),
        }
        self.store.save_changeset(changeset)
        event_type = {
            "verified": "changeset.verified",
            "partially_applied": "changeset.partially_applied",
            "failed": "changeset.failed",
        }.get(changeset.status, "changeset.verified")
        self.store.append_event(changeset_id=changeset.id, event_type=event_type, actor=actor, channel=channel, details={"status": changeset.status})
        activity_type = {
            "verified": "knowledge.change.verified",
            "partially_applied": "knowledge.change.partially_applied",
            "failed": "knowledge.change.failed",
        }.get(changeset.status, "knowledge.change.verified")
        self.service._activity().append(
            event_type=activity_type,
            title=f"{changeset.title}: {changeset.status.replace('_', ' ')}",
            course=changeset.course_id,
            source=f"{self.service.semester}/.academia/knowledge/change_journal.json",
            confidence="unverified",
            actor=actor,
            details={"changeset_id": changeset.id, "status": changeset.status, "operations": _operation_results(changeset)},
        )


def _topological(changeset: ChangeSet) -> list[Operation]:
    by_id = {operation.id: operation for operation in changeset.operations}
    ordered: list[Operation] = []
    visited: set[str] = set()

    def visit(operation: Operation) -> None:
        if operation.id in visited:
            return
        visited.add(operation.id)
        for dependency in operation.depends_on:
            visit(by_id[dependency])
        ordered.append(operation)

    for operation in changeset.operations:
        visit(operation)
    return ordered


def _operation_results(changeset: ChangeSet) -> list[dict[str, Any]]:
    return [
        {
            "operation_id": operation.id,
            "type": operation.type,
            "target": operation.target,
            "label": operation.label,
            "target_title": operation.target_title,
            "status": operation.status,
            "before": operation.before,
            "after": operation.after,
            "attempts": operation.attempts,
            "error": operation.last_error,
            "skip_effect_applied": operation.skip_effect_applied,
        }
        for operation in changeset.operations
    ]


def _result_summary(changeset: ChangeSet) -> str:
    verified = sum(operation.status == "verified" for operation in changeset.operations)
    failed = sum(operation.status in {"failed", "blocked", "conflict"} for operation in changeset.operations)
    skipped = sum(operation.status in {"skipped", "reversed", "already_reversed"} for operation in changeset.operations)
    parts = [f"{verified} verified"]
    if failed:
        parts.append(f"{failed} needing attention")
    if skipped:
        parts.append(f"{skipped} skipped or reversed")
    return " · ".join(parts)
