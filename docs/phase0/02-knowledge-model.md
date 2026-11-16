# 02 — Knowledge model and read contract

Status: **frozen for Phase 1**

## Purpose

The academic knowledge layer answers:

- What do we know about this course, assessment, deadline, task, or study record?
- Which source supports it?
- How confident and verified is it?
- What else disagrees?
- What is missing or stale?

Reading, retrieval, reasoning, and study do not require a ChangeSet.

## Entity set

Phase 1 deliberately models a small set. Extensibility comes from new fields and
relationships, not arbitrary JSON blobs.

| Entity | Identity | Canonical storage | Phase 1 |
| --- | --- | --- | --- |
| Course | existing course record ID | workspace course folder | read |
| Assessment | `assessment:history:<id>` or `assessment:domain:<id>` | history record or domain projection | read, deadline change |
| Deadline | `deadline:<id>` | assessment field for assessment deadlines; domain entity otherwise | read; projection alias only for assessments |
| Task | `task:<uuid>` | `SEMESTER_TASKS.md` | read, explicit link, due-date change |
| Study plan/session | existing `study.json` IDs | `study.json` | read-only; no deadline operation in Phase 1 |
| Evidence | `evidence:<uuid>` | `assertions.json` evidence list | append-only |
| Assertion | `assertion:<uuid>` | `assertions.json` | append-only |
| Task link | `link:<uuid>` | `links.json` | explicit create/pause |
| ChangeSet | `changeset:<uuid>` | `change_journal.json` | full lifecycle |
| Operation | `op:<uuid>` | inside its ChangeSet | full lifecycle |

### IDs

- Reuse existing stable IDs where they exist (history record UUID, task UUID,
  domain entity ID).
- New logical IDs are namespaced with a type prefix.
- IDs are never reused.
- An assessment's logical ID is derived from its `owner_locator`, not from its
  title. Titles can change.

## Relationships

```text
Course 1─* Assessment
Assessment 1─1 deadline owner field
Assessment 1─* TaskLink
Task 1─* TaskLink
TaskLink: mode = mirror_deadline | related
Assessment 1─* Assertion (subject)
Assertion *─* Evidence
ChangeSet 1─* Operation
Operation 1─1 target field revision
```

Rules:

- A task is affected by an assessment deadline change only when an explicit
  `mirror_deadline` link exists **and** the task's current due date equals the
  assessment's pre-change due date.
- A `related` link is informational. It never causes a task update.
- A `mirror_deadline` link whose task date has drifted is `diverged`. The task is
  not moved automatically. The conflict is surfaced.
- A link is created only by an explicit student action. Matching titles or dates
  do not create links.
- A link can be `active`, `paused`, or `removed`. Paused and removed links are
  preserved for history; they are not deleted.
- An assessment with no materialized record is `assertion_only`. It becomes
  materialized only through an approved ChangeSet.

## Assertion

An assertion is one claim about one field of one subject.

```json
{
  "id": "assertion:...",
  "subject": {"type": "assessment", "id": "assessment:history:..."},
  "field": "due_date",
  "value": "2026-11-20",
  "value_type": "date",
  "source_kind": "student_report",
  "authority_scope": ["assessment.due_date"],
  "specificity": "exact",
  "verification": "unverified",
  "confidence": "likely",
  "observed_at": "2026-11-16T15:00:00Z",
  "published_at": null,
  "supersedes": [],
  "conflicts_with": [],
  "applied_change_id": null,
  "status": "active",
  "created_at": "2026-11-16T15:00:00Z",
  "created_by": "user"
}
```

### Source kinds

```text
original_document
student_report
professor_announcement
ai_extraction
verified_external
legacy_record
external_edit
system_projection
```

### Verification

```text
verified
corroborated
unverified
disputed
```

### Confidence

Use the existing workspace vocabulary:

```text
current-confirmed
likely
unverified
historical
```

`current-confirmed` means the source is current and the student or an authorized
source confirmed it. It is not a synonym for migration output.

### Specificity

```text
exact
partial
approximate
unknown
```

### Status

```text
active
superseded
rejected
retracted
```

- Assertions are never deleted.
- Superseding an assertion appends `superseded_by` on the old record and
  `supersedes` on the new one.
- `rejected` means the student or an authorized process declined the claim. It
  remains visible for audit.
- `retracted` means the source withdrew the claim.
- `applied_change_id` records that the assertion was used to update an owner
  record. It does not change verification.

### Authority scope

`authority_scope` is a list of field patterns the source is authoritative for.
Examples:

```text
["assessment.due_date"]
["assessment.weight"]
["course.grading_policy"]
["assessment.due_date", "assessment.status"]
```

A recent professor announcement may be authoritative for `assessment.due_date`
but not for `assessment.weight`. AI extraction from a syllabus may be
authoritative for neither; it points to the syllabus evidence.

### Evidence

```json
{
  "id": "evidence:...",
  "source": "Professor announcement",
  "source_kind": "professor_announcement",
  "source_path": "Fall 2026/LSR 1100.../00_INBOX/announcement.pdf",
  "source_url": null,
  "locator": "page 1, paragraph 2",
  "excerpt": "The Second Essay deadline is now November 20.",
  "sha256": "...",
  "captured_at": "2026-11-16T15:00:00Z",
  "provenance": "EXTERNAL",
  "authority": "course instructor",
  "verification": "unverified"
}
```

Evidence is append-only. A student report can have no file path; `source` and
`source_kind` are still required.

## Effective value view

The read contract returns field-level resolved values, not a flat record that
hides uncertainty.

```json
{
  "assessment": {
    "id": "assessment:history:...",
    "course_id": "LSR 1100-A00 - Introduction to Leisure Studies",
    "title": "Second Essay",
    "kind": "essay",
    "owner": {"kind": "assignment_history", "locator": "..."},
    "fields": {
      "due_date": {
        "value": "2026-11-20",
        "resolution": "recorded",
        "confidence": "likely",
        "verification": "unverified",
        "source_kind": "student_report",
        "evidence": ["evidence:..."],
        "alternatives": [],
        "conflicts": [],
        "warnings": []
      },
      "weight": { "...": "..." }
    },
    "links": []
  },
  "conflicts": [],
  "warnings": []
}
```

Resolution values:

```text
recorded          owner record supplies the value
derived           no owner; assertions resolve to a leading candidate
conflict          owner value exists and an active assertion disagrees
needs_confirmation  assertions disagree and cannot be separated safely
inconsistent      an applied assertion no longer matches the owner
missing           no value is known
```

`value` may be non-null even when `resolution` is `conflict` or
`needs_confirmation`. Consumers must not present that value as settled.

## Read operations

The Phase 1 interface exposes:

```text
knowledge.course_view(course_id)
knowledge.assessment_view(assessment_id)
knowledge.conflicts(course_id)
knowledge.links(course_id)
```

### `course_view`

Returns:

- course identity;
- assessments with resolved fields;
- conflicts and missing fields;
- task links;
- warnings about stale or unindexed records;
- migration status.

It does not return full source bodies. Source retrieval remains a separate
bounded operation.

### `assessment_view`

Returns one assessment, its owner, resolved fields, evidence, alternatives,
links, and any related ChangeSets.

### `conflicts`

Returns only unresolved conflicts:

```json
{
  "id": "conflict:...",
  "subject": {"type": "assessment", "id": "..."},
  "field": "due_date",
  "owner_value": "2026-11-12",
  "assertions": [],
  "recommended_resolution": "needs_confirmation",
  "why": "A recent student report disagrees with the recorded deadline.",
  "available_actions": ["propose_change", "keep_current", "inspect_evidence"]
}
```

### `links`

Returns explicit task links with mode, status, last synchronized value, and
divergence warnings.

## Conflict behavior

- Conflicts are first-class records in the read model. They are not errors.
- A conflict never triggers an automatic write.
- The agent may explain the conflict and propose a ChangeSet.
- The student decides.
- A conflict remains visible after a change if the underlying assertions still
  disagree. Applying a value does not erase the evidence that disagreed.

## Missing and stale data

- Missing fields are reported as `missing`, not invented.
- A source hash mismatch produces `stale_source`.
- A canonical record changed outside the engine produces
  `unindexed_external_change`.
- A task link whose date no longer matches produces `diverged`.
- A ChangeSet proposal against a stale record must revalidate before execution.

## Extensibility

Phase 1 does not add arbitrary fields to assessments. New academic concepts
should be added as:

1. a new entity with a stable ID and canonical owner;
2. a new field policy;
3. a new operation type with validation, verification, and reversal semantics.

Do not extend the model by storing unstructured JSON in an assertion value.

## Related contracts

- [01-sources-of-truth.md](01-sources-of-truth.md)
- [03-change-coordination.md](03-change-coordination.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
