# 06 — User experience contract for the first slice

Status: **frozen for Phase 1**

## Scope

Phase 1 adds one reusable ChangeSet experience to the existing course
workspace. It does not redesign navigation, Home, Planner, or the Agent.

The entry point is the course **History** view:

```text
Course → History → coursework record → Change deadline
```

The existing History editor, task editor, Review queue, and Study views remain
available and unchanged.

## Student promise

A student can say or enter:

> “My professor moved the Second Essay deadline to November 20.”

and see:

1. the exact assessment being changed;
2. the current and proposed dates;
3. where the information came from;
4. every task that will move, and every task that will not;
5. any conflict or warning;
6. a clear approval step;
7. a verified result, or an honest partial/failed state;
8. an undo option when reversal is genuinely supported.

## Flow

### 1. Start a change

On a coursework record with a deadline, the student selects **Change deadline**.
The form asks for:

- the new date (required);
- the source: **Student report**, **Professor announcement**, or **Other**;
- an optional note or source reference;
- an optional evidence file from the course material (for a professor
  announcement or screenshot).

The form never changes the record directly.

### 2. Preview

The preview shows:

```text
Second Essay
Due Nov 12 → Nov 20

Evidence
Student report · unverified · recorded today
[optional source reference]

This change will update
[✓] Second Essay deadline (required)
[✓] Task: Finish Second Essay (mirrors this deadline)
[✓] Task: Print submission (mirrors this deadline)

Not affected
2 other tasks in this course have different dates.

Warnings
The syllabus says Nov 12. This report is newer but unverified.
The change will be recorded as student-reported, not verified.

[Cancel] [Approve selected and apply]
```

Rules:

- The assessment deadline is always selected and cannot be unchecked.
- Mirrored tasks default to selected. Unchecking one shows:
  **“This task will keep its current date and stop mirroring the assessment.”**
- Related tasks and unlinked tasks are listed only as context, never as
  selected operations.
- A diverged mirror is shown as a warning, not silently moved.
- Conflicts are shown with both values and evidence. The preview never claims
  the new value is confirmed.
- Irreversible operations are labeled before approval.

### 3. Approve and apply

- The button says **Approve selected and apply**.
- The approval records the exact operation set and payload hash.
- Execution starts immediately in the same local flow.
- The UI never reports success before read-back verification.

### 4. Result

Success:

```text
Deadline updated
Second Essay: Nov 12 → Nov 20
Task: Finish Second Essay: Nov 12 → Nov 20
Task: Print submission: Nov 12 → Nov 20

Recorded as student-reported · unverified
2 operations verified · Activity recorded
[Undo this change]
```

Skipped:

```text
Task: Print submission was not changed.
Its deadline link is paused. The task stays independent until you link it again.
```

Partial failure:

```text
Deadline updated, but one task could not be updated.
2 verified · 1 failed
The task still shows Nov 12.
[Retry failed] [Review details]
```

Failure:

```text
No changes were applied.
The assessment deadline could not be updated.
[Retry] [Cancel]
```

Conflict or crash recovery:

```text
This change needs your review.
The record changed after the preview was created.
Current: Nov 15
Proposed: Nov 20
[Repropose] [Keep current]
```

### 5. Undo

- **Undo this change** appears only when every executed operation is reversible.
- If any operation is irreversible, the UI lists it and does not promise full
  undo.
- Undo revalidates every target. If a later student edit changed a target, undo
  stops and explains which record changed.
- Undo preserves the original audit history and adds reversal entries.
- Paused links are not silently reactivated. Re-linking is a separate explicit
  student action and is not performed by the result screen.

## Component contract

The preview is a reusable component with these props/states:

```text
changeset
  summary
  operations[]
  evidence[]
  conflicts[]
  warnings[]
  impact
  approval
  result
  reversal

onApprove(selectedOperationIds)
onCancel()
onRetryFailed()
onReverse()
onResumeLink(linkId)
```

It must be usable for a future calendar or study-plan operation without
redesigning the page.

## Presentation rules

- Use plain academic language, not engine terminology, in the primary UI.
  “Deadline,” “task,” “source,” “verified,” and “not verified” are appropriate.
  “Assertion,” “ChangeSet,” and “operation journal” are internal terms.
- Show the owner record: “Recorded in this course’s History.”
- Show the evidence label exactly: `student-reported`, `unverified`,
  `corroborated`, `verified`, `disputed`.
- Do not use a green success style for an unverified fact. Verification and
  completion are different badges.
- Destructive or irreversible actions require a distinct confirmation.
- Keyboard: the dialog is reachable, focus-trapped, closes with Escape, and
  returns focus to the trigger.
- Screen readers: the before/after values, selection state, warnings, and result
  are announced.
- Mobile/narrow layout is not a Phase 1 requirement; the existing responsive
  behavior should not regress.

## Empty and missing states

- No deadline: **“This record has no deadline yet. Add one in History first.”**
- No linked tasks: **“No tasks mirror this deadline.”**
- No evidence file: **“Student report · unverified”** is sufficient.
- No study plan: no study-plan section is shown. Phase 1 does not invent one.

## What the UI must not do

- It must not silently apply a change.
- It must not auto-select a conflicting source.
- It must not imply that a student report is verified.
- It must not move an unlinked task.
- It must not hide skipped or failed operations.
- It must not offer “Undo” for irreversible operations.
- It must not replace the existing History editor.
- It must not add a fifth primary navigation area.

## Related contracts

- [03-change-coordination.md](03-change-coordination.md)
- [04-permissions-and-safety.md](04-permissions-and-safety.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
