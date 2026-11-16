# 03 — Change coordination contract

Status: **frozen for Phase 1**

## Purpose

A ChangeSet is a structured proposal to change academic records. It is not a
database transaction and it is not the read model.

It answers:

- What does the student want to change?
- Which records are affected?
- What is required, optional, or dependent?
- What evidence supports it?
- Who approved what?
- What succeeded, failed, needs retry, or can be reversed?

## Lifecycle

```text
draft → proposed → approved → executing → verified
                         ↘ partially_applied → retry → verified
                         ↘ failed → retry → partially_applied/verified
verified/partially_applied → reverted / partially_reverted / reversal_conflict
proposed/approved → cancelled
proposed → superseded
```

Statuses:

| Status | Meaning |
| --- | --- |
| `draft` | Being built; not ready for approval |
| `proposed` | Preview is complete and waiting for a student decision |
| `approved` | At least one operation is approved; execution may start |
| `executing` | At least one operation is in progress |
| `verified` | Every approved, non-skipped operation verified |
| `partially_applied` | Some approved operations verified; others failed or are blocked |
| `failed` | No approved operation verified |
| `cancelled` | Student cancelled before execution |
| `reverted` | Every reversible operation was reversed and verified |
| `partially_reverted` | Some operations reversed; others conflicted or are irreversible |
| `reversal_conflict` | Reversal stopped because a target changed after execution |
| `superseded` | A newer ChangeSet replaced this one before execution |

## ChangeSet schema

```json
{
  "id": "changeset:...",
  "version": 1,
  "title": "Move Second Essay deadline to November 20",
  "course_id": "LSR 1100-A00 - Introduction to Leisure Studies",
  "semester": "Fall 2026",
  "origin": "student_request",
  "status": "proposed",
  "created_at": "2026-11-16T15:00:00Z",
  "updated_at": "2026-11-16T15:00:00Z",
  "created_by": "user",
  "summary": "Update the assessment deadline and explicitly mirrored task dates.",
  "evidence_ids": ["evidence:..."],
  "operations": [],
  "conflicts": [],
  "warnings": [],
  "impact": {
    "required_operations": ["op:..."],
    "optional_operations": ["op:..."],
    "irreversible_operations": [],
    "affected_entities": [],
    "summary": "1 assessment, 2 mirrored tasks"
  },
  "approval": {
    "status": "pending",
    "mode": null,
    "approved_operation_ids": [],
    "approved_by": null,
    "approved_at": null,
    "channel": null,
    "version": null,
    "approval_hash": null,
    "note": null
  },
  "execution": {
    "journal_id": "changeset:...",
    "started_at": null,
    "completed_at": null,
    "last_actor": null,
    "attempts": 0
  },
  "result": {
    "state": "not_started",
    "operation_results": [],
    "summary": null
  },
  "reversal": {
    "status": "not_requested",
    "requested_at": null,
    "approved_by": null,
    "completed_at": null,
    "operation_results": []
  }
}
```

## Operation schema

```json
{
  "id": "op:...",
  "type": "assessment.set_deadline",
  "target": {
    "entity_type": "assessment",
    "entity_id": "assessment:history:...",
    "owner_kind": "assignment_history",
    "owner_locator": "Fall 2026/.../03_ASSIGNMENTS/Assignment_History.json#<record-id>",
    "field": "due_date"
  },
  "before": "2026-11-12",
  "after": "2026-11-20",
  "depends_on": [],
  "required": true,
  "default_selected": true,
  "reversible": true,
  "sync_basis": null,
  "skip_effect": null,
  "expected_revision": "sha256:...",
  "idempotency_key": "sha256:...",
  "evidence_ids": ["evidence:..."],
  "status": "proposed",
  "attempts": 0,
  "last_error": null,
  "result": null
}
```

### Operation types in Phase 1

| Type | Required | Reversible | Notes |
| --- | --- | --- | --- |
| `assessment.set_deadline` | yes | yes | Writes the single assessment owner field |
| `task.set_due` | no, default selected | yes | Only for an explicit `mirror_deadline` link whose current date equals the assessment's before date |
| `study_plan.reschedule` | reserved | yes | Not generated in Phase 1 because no canonical study-plan record exists |

No other operation types are accepted in Phase 1.

### Required and optional operations

- Exactly one `assessment.set_deadline` operation is required for a deadline
  ChangeSet. It cannot be deselected. The student can cancel the whole
  ChangeSet instead.
- Each explicitly mirrored task is an optional operation with
  `default_selected: true`. The student may deselect it. Deselecting has the
  explicit `skip_effect: pause_link`; the task keeps its old date and the link
  becomes `paused`. This avoids silently leaving an active mirror that no longer
  mirrors.
- A task with a `related` link, an unlinked task, or an independent milestone is
  never included.
- A mirrored task whose current due date does not equal the assessment's
  pre-change due date is `diverged`. It is not included; the preview reports a
  warning and offers no automatic update.
- Dependencies must be acyclic. A dependent operation cannot execute until every
  dependency is `verified`.
- An operation may not widen its own scope. The executor rejects any attempt to
  write a field or target not described by the operation.

### Idempotency key

The key is a SHA-256 over:

```text
changeset id + operation id + target + before + after + expected revision
```

It is stable across retries and is recorded in the journal. Reusing it never
applies a second write.

### Expected revision

`expected_revision` is a content hash of the target record's canonical fields at
proposal time. The executor recomputes it before writing.

- If the revision matches, the operation may proceed.
- If it does not match and the target already equals `after`, the operation is
  verified idempotently.
- If it does not match and the target equals neither `before` nor `after`, the
  operation is a conflict and is not written.

## Approval

Approval is a student decision. It is separate from verification.

```json
{
  "status": "approved | partially_approved | rejected | pending",
  "mode": "full | partial",
  "approved_operation_ids": ["op:..."],
  "approved_by": "user",
  "approved_at": "...",
  "channel": "dashboard | cli_user",
  "version": 1,
  "approval_hash": "sha256:...",
  "note": null
}
```

Rules:

1. The agent may create a ChangeSet. It may not approve it.
2. Only `user`/`student` actors on a user channel may approve.
3. The approval hash covers the version, operation IDs, targets, before/after
   values, required flags, and evidence IDs.
4. Any amendment increments `version`, clears approval, and returns the
   ChangeSet to `proposed`. An old approval can never authorize a new payload.
5. `mode: full` approves every operation. `mode: partial` approves the required
   operation plus the selected optional operations.
6. If the student deselects an optional mirrored task, the approval records
   `skip_effect: pause_link`, and execution pauses that link.
7. Approval of a ChangeSet is not verification of the academic fact.

## Execution

Execution is a durable, resumable sequence, not a single transaction.

### Sequence per operation

1. Validate ChangeSet status, approval hash, version, dependencies, and
   operation selection.
2. Append `operation.executing` to the journal.
3. Re-read the target and recompute its revision.
4. If the target equals `after`, mark `verified` without writing.
5. If the target does not equal `before`, mark `conflict` and stop dependents.
6. Apply the write with the canonical store's atomic/locked operation.
7. Read the target back.
8. If the read-back equals `after`, mark `verified`.
9. If not, mark `failed` with `verification_failed`.
10. Append the result event.

### Partial failure

- Verified operations stay verified.
- Failed operations remain retryable.
- Dependents of a failed operation become `blocked`.
- Optional operations that were not approved stay `skipped`.
- The ChangeSet is `partially_applied` if at least one approved operation
  verified and at least one failed or is blocked.
- The ChangeSet is `failed` if no approved operation verified.
- The UI shows the exact state and offers **Retry failed**.

### Retry

- Retry only operations in `failed` or `blocked` whose dependencies are now
  verified.
- Revalidate approval, version, revision, and before/after values.
- Never reapply a verified operation.
- Never retry a `conflict` automatically; the student must resolve it.

### Crash recovery

The journal is written before the target write. On restart:

1. Load every ChangeSet in `executing` or `approved`.
2. For each operation in `executing`:
   - if the target equals `after`, mark `verified`;
   - if the target equals `before`, retry within the attempt limit;
   - if neither, mark `conflict`.
3. Recompute the ChangeSet status from operation states.
4. Append a `changeset.recovered` event.
5. Never duplicate a write that already reached `after`.

Crash recovery is idempotent. Running it twice produces the same state.

### Attempts and errors

- Default maximum attempts per operation: 3.
- Each attempt records actor, timestamp, error class, and message.
- A failure remains visible until retry, cancellation, or reversal.
- A failed action is never reported as successful.

## Reversal

Reversal is conditional and preserves audit history.

- Only operations marked `reversible: true` can be reversed.
- A reversal is a student decision. The agent may propose it but may not approve
  or execute it in Phase 1.
- Reversal runs in reverse dependency order.
- For each operation:
  - if the target equals `before`, mark `already_reversed`;
  - if the target equals `after`, write `before` and verify;
  - if the target is neither, mark `reversal_conflict` and stop that branch;
  - never overwrite a later student change.
- Original execution events remain. Reversal appends new events; it does not
  delete or rewrite history.
- If the link was paused by a skipped task operation, reversal does not
  automatically reactivate it. Reactivation is a separate explicit student
  action.
- ChangeSet status becomes `reverted`, `partially_reverted`, or
  `reversal_conflict`.
- Irreversible operations are listed in `impact.irreversible_operations` and are
  never presented as undoable.

## Journal

`change_journal.json` stores the current ChangeSet records and an append-only
event list in one atomically written file.

Event types:

```text
changeset.created
changeset.proposed
changeset.amended
changeset.approved
changeset.rejected
changeset.execution_started
operation.executing
operation.verified
operation.failed
operation.conflict
operation.skipped
operation.blocked
changeset.partially_applied
changeset.verified
changeset.failed
changeset.recovered
changeset.reversal_requested
operation.reversed
operation.reversal_conflict
changeset.reverted
changeset.partially_reverted
changeset.reversal_conflict
changeset.cancelled
```

Each event includes:

```json
{
  "id": 12,
  "at": "2026-11-16T15:05:00Z",
  "changeset_id": "changeset:...",
  "operation_id": "op:...",
  "type": "operation.verified",
  "actor": "user",
  "channel": "dashboard",
  "details": {}
}
```

Events are never edited or deleted. The ChangeSet snapshot is the current state;
the event list is the audit trail. They are written together so they cannot
diverge.

## Activity

The engine appends summary events to the existing Activity feed:

```text
knowledge.change.proposed
knowledge.change.approved
knowledge.change.verified
knowledge.change.partially_applied
knowledge.change.failed
knowledge.change.reversed
knowledge.change.reversal_conflict
```

Activity is the cross-feature change feed. It does not replace the ChangeSet
journal.

## Non-guarantees

- No universal atomicity across unrelated stores.
- No universal undo.
- No automatic propagation to external services in Phase 1.
- No agent self-approval.
- No silent conflict resolution.

## Related contracts

- [04-permissions-and-safety.md](04-permissions-and-safety.md)
- [06-ux-contract.md](06-ux-contract.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
