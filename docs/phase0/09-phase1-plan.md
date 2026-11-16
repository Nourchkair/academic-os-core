# 09 — Phase 1 implementation plan

Status: **implemented on `next/academic-engine`; validated locally, not merged or released**

## Goal

Ship one dependable local workflow:

> A student reports an assessment deadline change. AcademiaOS resolves the
> assessment, previews the impact on explicitly mirrored tasks, accepts full or
> partial approval, applies the change, verifies every operation, records the
> result, recovers from interruption, and can conditionally reverse the change.

No Google Calendar. No broad intake. No navigation redesign. No release.

## Work breakdown

### 1. Knowledge store and model

**Deliverables**

- `academia_os/knowledge/` package.
- Atomic stores for `assertions.json`, `links.json`, `change_journal.json`, and
  `schema.json`.
- Dataclasses and validation for evidence, assertions, task links, ChangeSets,
  operations, and journal events.
- Corruption handling: fail closed or quarantine; never silently reset.
- Migration from `Assignment_History.json`, `domain.json`, and tasks.

**Tests**

- K1–K10, L1–L7, M1–M9.

**Estimate:** 2–3 engineering days.

### 2. Effective-value resolver

**Deliverables**

- Field policy for `assessment.due_date`.
- Owner precedence: history > domain projection > assertion-only.
- Assertion comparison using scope, verification, source authority, specificity,
  and recency.
- Conflict, inconsistent, missing, and stale-source states.
- Course and assessment read views.

**Tests**

- K1–K10, M11.

**Estimate:** 1–2 engineering days.

### 3. ChangeSet proposal and preview

**Deliverables**

- Resolve a course/assessment by exact ID or unique title.
- Append a student-report or professor-announcement assertion.
- Build the required assessment operation.
- Include only valid `mirror_deadline` tasks; detect divergence.
- Compute impact, warnings, conflicts, and reversible labels.
- Approval hashing and version invalidation.

**Tests**

- C1, C5, C6, C13; L1–L6; golden scenario preview.

**Estimate:** 1–2 engineering days.

### 4. Local execution engine

**Deliverables**

- Operation executors for `assessment.set_deadline` and `task.set_due`.
- Expected revision checks.
- Durable journal states and events.
- Idempotency keys.
- Dependency ordering and blocked dependents.
- Read-back verification.
- Crash recovery.
- Retry only failed/blocked operations.
- Conditional reversal.
- Activity summaries.

**Tests**

- C2–C12, R1–R9, P1–P8.

**Estimate:** 3–4 engineering days.

### 5. CLI and local API

**Deliverables**

```text
academia knowledge view --course COURSE --semester TERM --json
academia knowledge assessment ASSESSMENT_ID --semester TERM --json
academia knowledge conflicts --course COURSE --semester TERM --json
academia knowledge migrate --semester TERM [--refresh] --json
academia change propose-deadline --course COURSE --assessment ID \
  --new-date YYYY-MM-DD --source-kind student_report|professor_announcement \
  --evidence-path PATH --evidence-locator TEXT --evidence-excerpt TEXT \
  --actor user --json
academia change link-task --course COURSE --assessment ID --task TASK_ID \
  --mode mirror_deadline|related --actor user --json
academia change pause-link LINK_ID --actor user --json
academia change list --semester TERM --json
academia change show CHANGESET_ID --json
academia change amend CHANGESET_ID --new-date YYYY-MM-DD --note TEXT --actor user --json
academia change approve CHANGESET_ID --operations OP_ID... --actor user --json
academia change execute CHANGESET_ID --json
academia change retry CHANGESET_ID --json
academia change cancel CHANGESET_ID --actor user --json
academia change reverse CHANGESET_ID --actor user --json
```

Local HTTP routes through the existing `/api/v1/command` bridge and dedicated
read endpoints for the dashboard.

**Tests**

- CLI JSON shapes, error codes, actor enforcement, web route tests.

**Estimate:** 1–2 engineering days.

### 6. Impact-preview UI

**Deliverables**

- **Change deadline** action on a coursework record.
- `DeadlineChangeDialog` with form → preview → result states.
- Required/optional operation selection.
- Evidence, conflict, divergence, and verification badges.
- Partial-failure and retry states.
- Conditional undo and pause-link messaging.
- Styles that fit the existing course workspace.
- Focus trap, Escape, and accessible labels.

**Tests**

- U1–U8.
- At least one component/helper test for operation selection and warning text.
- Manual walkthrough on a copied workspace.

**Estimate:** 2–3 engineering days.

### 7. Validation and hardening

**Deliverables**

- Full Python suite.
- Frontend test, typecheck, and build.
- Manual walkthrough with a real course copy.
- Simulated crash, failed task write, and later-edit reversal conflict.
- Performance check on the configured workspace.
- No regressions in existing History, Tasks, Review, Study, Library, Agent
  context, or MCP reads.

**Estimate:** 1–2 engineering days.

## Total estimate

**11–18 engineering days** for a careful local slice. The range is dominated by
crash/reversal tests and UI states, not by the happy path.

## Implementation order

1. Contracts and fixtures.
2. Store and migration.
3. Resolver and read view.
4. Proposal and preview data.
5. Execution, journal, recovery, reversal.
6. CLI and local API.
7. UI.
8. Full validation.

Do not start UI before the preview/execution JSON is stable. Do not start
Google Calendar before the local slice passes R1–R9.

## Files and integration points

New:

```text
academia_os/knowledge/
  __init__.py
  model.py
  store.py
  resolver.py
  service.py
  executor.py
  cli.py
tests/test_knowledge_model.py
tests/test_knowledge_changes.py
tests/test_knowledge_cli.py
frontend/src/DeadlineChange.tsx
frontend/src/lib/deadline-change.ts
```

Targeted changes:

```text
academia_os/cli.py                     register knowledge/change commands
academia_os/web.py                     dashboard routes or command bridge entries
academia_os/assignment_history.py      expected-before deadline update
academia_os/tasks.py                   expected-before due-date update
frontend/src/CourseworkHistory.tsx     entry point and refresh
frontend/src/lib/api.ts                typed calls
frontend/src/types.ts                  ChangeSet/preview types
frontend/src/styles.css                dialog and result styles
frontend/src-tauri/src/lib.rs          desktop command allowlist
tests/test_web.py                      route coverage
```

No changes to source-of-truth file schemas in Phase 1.

## Design constraints during implementation

- The history record remains the owner of its deadline.
- A domain deadline is never a second owner for an assessment.
- A task moves only through an explicit `mirror_deadline` link and only when its
  current date matches the assessment's before date.
- `related`, unlinked, and independent tasks never move.
- A skipped mirrored task pauses its link.
- Approval and verification are separate.
- A student report stays unverified after approval.
- The agent cannot approve or reverse.
- Crash recovery never duplicates a write.
- Reversal never overwrites a later student change.
- If a feature cannot be made dependable, cut it from the slice rather than
  faking it. In particular, do not invent a study-plan record just to produce an
  optional operation.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Scope creep into calendar/intake | Hard non-goals; local executors only |
| Duplicate deadline records | Owner locator rule; projection aliases |
| False confidence | Separate approval/verification; unverified labels |
| Crash duplicates a write | Journal-before-write; after-state idempotency |
| Partial failure hides data | Per-operation results; status `partially_applied` |
| Reversal overwrites later edits | Revision check; `reversal_conflict` |
| Legacy migration invents confirmation | `legacy_record`, `unverified`, preserved basis |
| UI implies success before verification | Render only read-back results |
| Branch divergence | Merge `main` regularly; release only from `main` |

## Beta gate

After the slice passes and is manually validated on a copied workspace, start a
small design-partner test. Do not wait for the full five-phase roadmap. The beta
gate checks:

- the student can complete the flow without developer help;
- the preview is understandable;
- no silent changes occur;
- failures and unverified facts are clear;
- the student trusts the result enough to use it again.

## Explicitly not in this plan

- Google Calendar execution.
- Calendar partial-failure across services.
- Study-plan recalculation.
- A general academic graph.
- Agent approval or trusted auto-apply.
- A navigation redesign.
- A release or installed-app update.

## Related contracts

- [README.md](README.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
- [07-non-goals.md](07-non-goals.md)
