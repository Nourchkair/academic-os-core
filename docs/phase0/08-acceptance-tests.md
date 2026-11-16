# 08 — Acceptance tests

Status: **required for Phase 1**

The first vertical slice is complete only when every scenario below passes in
automated tests and a local manual walkthrough.

## Golden scenario

> “My professor moved the Second Essay deadline from November 12 to
> November 20.”

Fixture:

- one course with a history record `Second Essay`, `due_date: 2026-11-12`;
- two open tasks in the same course with due date `2026-11-12`, explicitly
  linked as `mirror_deadline`;
- one independent task in the same course with due date `2026-11-15`, linked as
  `related` or unlinked;
- a syllabus evidence record asserting `2026-11-12`.

Expected:

1. The course and assessment resolve exactly.
2. A student-report assertion is appended: `2026-11-20`, `student_report`,
   `unverified`, `likely`.
3. The ChangeSet contains:
   - required `assessment.set_deadline`;
   - two optional, default-selected `task.set_due` operations;
   - no operation for the independent task.
4. The preview shows the syllabus conflict and the independent task as not
   affected.
5. Full approval applies all three operations.
6. Each operation is read back and `verified`.
7. The history record due date is `2026-11-20`.
8. Both mirrored task due dates are `2026-11-20`.
9. The independent task is unchanged.
10. Activity records the proposal, approval, and verified result.
11. The assertion remains `unverified`; approval did not verify the fact.
12. Re-reading the assessment returns `2026-11-20` with the student-report
    evidence and the older syllabus assertion as an alternative/conflict.

## Required scenarios

### K — Knowledge model

| ID | Scenario | Expected |
| --- | --- | --- |
| K1 | History-owned assessment with a due date | Effective value is the history value; resolution `recorded` |
| K2 | Domain-only assessment with a deadline | Effective value is the domain projection; owner kind `domain_projection` |
| K3 | Assertion-only assessment with one exact assertion | Value is `derived` |
| K4 | Two active assertions disagree and cannot be separated | Resolution `needs_confirmation`; both alternatives preserved |
| K5 | Verification outranks recency | Verified older assertion leads an unverified newer one |
| K6 | Recency breaks a tie within the same authority/verification | Newer assertion leads |
| K7 | Authority scope does not include the field | Assertion is not a candidate |
| K8 | Applied assertion no longer matches owner | Resolution `inconsistent`; owner value returned |
| K9 | Source hash changed outside the engine | `stale_source` / `unindexed_external_change` warning; no silent write |
| K10 | Assessment and deadline projection disagree | Assessment wins; conflict is visible; no duplicate owner |

### L — Links

| ID | Scenario | Expected |
| --- | --- | --- |
| L1 | No explicit link, matching date | Task is not affected |
| L2 | `related` link | Task is not affected |
| L3 | `mirror_deadline` link, date matches before value | Task is included |
| L4 | `mirror_deadline` link, date diverged | Task is not moved; `diverged` warning |
| L5 | Student deselects a mirrored task | Task unchanged; link becomes `paused`; warning shown |
| L6 | Link paused by a previous change | Later deadline changes do not include it |
| L7 | Link resumed explicitly | Later changes include it again |

### C — ChangeSet lifecycle

| ID | Scenario | Expected |
| --- | --- | --- |
| C1 | Propose a deadline change | Status `proposed`; no canonical file changed |
| C2 | Approve required + all optional | Status `approved`; approval hash recorded |
| C3 | Approve required + subset | Status `approved`; skipped optional task pauses its link |
| C4 | Approve with no required operation | Rejected |
| C5 | Amend after approval | Version increments; approval cleared; status `proposed` |
| C6 | Execute with stale approval hash | Rejected; no write |
| C7 | Execute an unapproved operation | Rejected |
| C8 | Execute twice | Second run is idempotent; no duplicate writes/events |
| C9 | Required operation fails | Dependents blocked; status `failed`/`partially_applied` as appropriate |
| C10 | Optional task fails, assessment verifies | Status `partially_applied`; task remains retryable |
| C11 | Retry failed operation | Only failed/blocked operations run; verified ones are not reapplied |
| C12 | Cancel before execution | Status `cancelled`; no canonical change |
| C13 | Unknown assessment/task | Structured error; no fallback to another course |

### R — Recovery and reversal

| ID | Scenario | Expected |
| --- | --- | --- |
| R1 | Crash after `operation.executing`, before write | Recovery sees `before`; retries safely |
| R2 | Crash after write, before verification | Recovery sees `after`; marks verified without rewriting |
| R3 | Crash during recovery | Second recovery is idempotent |
| R4 | Reverse a fully verified ChangeSet | All reversible operations return to `before`; status `reverted`; audit preserved |
| R5 | Reverse after a later student edit | `reversal_conflict`; later edit is not overwritten |
| R6 | Reverse a partially applied ChangeSet | Verified reversible operations reverse; failed ones remain failed |
| R7 | Reverse an irreversible operation | Not offered; listed as irreversible |
| R8 | Reverse twice | Second run is idempotent; no duplicate writes |
| R9 | Reverse a change that paused a link | Link stays paused; resume is separate |

### P — Permissions

| ID | Scenario | Expected |
| --- | --- | --- |
| P1 | Agent proposes | Allowed; actor/channel recorded |
| P2 | Agent approves its own proposal | `PermissionError`; status unchanged |
| P3 | MCP/assistant channel approves | Rejected |
| P4 | Agent executes an approved ChangeSet | Allowed if approval valid |
| P5 | Agent executes an unapproved ChangeSet | Rejected |
| P6 | Agent reverses | Rejected in Phase 1 |
| P7 | Student approves via dashboard/CLI user path | Allowed; actor/channel recorded |
| P8 | Agent creates a task link without student confirmation | Rejected |

### M — Migration and compatibility

| ID | Scenario | Expected |
| --- | --- | --- |
| M1 | Migrate a history record with `record_basis: user-confirmed` | Assertion is `legacy_record`, `verification: unverified`; original basis preserved as legacy metadata |
| M2 | Migrate a domain assignment with no history record | Domain projection owner; no duplicate assessment |
| M3 | Migrate a domain assignment that uniquely matches history | Projection alias; one assessment |
| M4 | Migrate ambiguous duplicate titles | Both remain; warning; no silent merge |
| M5 | Migrate a domain deadline matching an assessment | Projection alias; assessment owns the date |
| M6 | Migrate matching dates/titles between tasks and assessments | No links created |
| M7 | Re-run migration | Idempotent; no duplicate assertions |
| M8 | External edit after migration | Detected; no overwrite; explicit refresh appends `external_edit` |
| M9 | Workspace without `.academia/knowledge/` | Existing commands and UI work unchanged |
| M10 | Backup/restore | Knowledge store restored with the workspace |
| M11 | Candidate deadline conflict during proposal | Review/conflict visible; no silent overwrite |
| M12 | Agent cannot self-approve | Covered by P2/P3 |

### U — UI

| ID | Scenario | Expected |
| --- | --- | --- |
| U1 | History record → Change deadline | Dialog opens with current date |
| U2 | Preview with two mirrored tasks | Both selected by default |
| U3 | Deselect one task | Warning explains pause; task omitted from approval |
| U4 | Approve and apply | Result shows verified values and unverified badge |
| U5 | Simulated task failure | Result shows partial state and Retry failed |
| U6 | Undo | Undo appears only when reversible; conflict state explains changed record |
| U7 | Escape/focus | Dialog closes, focus returns to trigger |
| U8 | Existing History edit | Still works without using the engine |

## Manual walkthrough

On a copy of a real workspace:

1. Start the local dashboard from the `next/academic-engine` worktree.
2. Open a course with a history record and a mirrored task.
3. Record a deadline change with a student report.
4. Inspect the preview: evidence, required/optional, warnings.
5. Deselect one task; approve.
6. Verify the assessment and selected task changed; the deselected task did not;
   its link is paused.
7. Open the result and inspect Activity.
8. Undo; verify the original dates return and the journal retains both states.
9. Repeat with a simulated failure and confirm retry only affects the failed
   operation.
10. Confirm the History editor still works independently.

## Test data rules

- Use temporary workspaces; do not modify the user’s real workspace in tests.
- Use fixed dates and UUIDs where the assertion is about ordering.
- Include a fixture with no `.academia` directory.
- Include a fixture with a corrupt knowledge file; reads must fail closed or
  quarantine, never silently reset.
- Include a fixture with a legacy `domain.json` deadline duplicate.
- Include a fixture with an external edit between proposal and execution.

## Definition of done

- All Python tests pass, including the new knowledge/change suites.
- Existing Python tests continue to pass.
- Frontend typecheck and build pass.
- Existing frontend tests pass; new UI behavior is covered by at least one
  component or helper test.
- No release, merge, or installed-app update occurs without explicit approval.

## Related contracts

- [03-change-coordination.md](03-change-coordination.md)
- [05-migration-and-compatibility.md](05-migration-and-compatibility.md)
- [09-phase1-plan.md](09-phase1-plan.md)
