# 01 — Sources of truth and effective values

Status: **frozen for Phase 1**

## Decision

Existing academic files remain canonical for their domains. The knowledge layer
does not copy those values into a second editable record.

The knowledge layer stores four things:

1. **Evidence** — where a claim came from.
2. **Assertions** — what a source or person said about one field.
3. **Relationships** — which records are explicitly linked.
4. **ChangeSets and journals** — what was proposed, approved, executed, verified,
   failed, or reversed.

The current academic value is **resolved** from the canonical owner record and
the active assertions. It is not stored as a second mutable truth.

## Canonical ownership

| Domain | Canonical record | Knowledge layer role |
| --- | --- | --- |
| Coursework/assessment identity, status, grade, submitted date | `SEMESTER/COURSE/03_ASSIGNMENTS/Assignment_History.json` | Link evidence and assert fields; never duplicate the record |
| Assessment deadline for a history-owned assessment | `Assignment_History.json` → record `due_date` | Resolve effective value; store assertions and conflicts |
| Extracted assessment with no history record | `.academia/domain.json` → assignment entity | Resolve effective value; mark as a projection owner |
| User tasks and their due dates | `SEMESTER/SEMESTER_TASKS.md` | Store explicit links; never copy tasks into assertions |
| Study sets, sessions, attempts, review schedule, exam scope | `SEMESTER/COURSE/06_KNOWLEDGE/STUDY/study.json` | Read-only for Phase 1; no deadline ownership |
| Original documents | Course folder files | Immutable evidence; never rewritten by a ChangeSet |
| Calendar events | Google Calendar (future) | Not in Phase 1 |

`domain.json` is a derived projection of extracted academic entities. It is a
canonical **storage owner only when no `Assignment_History.json` record exists**
for that assessment. This avoids creating two editable assessments with the same
identity.

## Assessment and Deadline ownership

This is the rule that prevents duplicate deadlines:

> An assessment has exactly one deadline owner. A `Deadline` record is never a
> second owner of an assessment deadline.

### Assessment

The logical `Assessment` is the academic entity for an assignment, essay,
project, exam, presentation, quiz, or other graded work. It has one
`owner_locator`:

```text
assignment_history:<record_id>     # preferred when a history record exists
domain_projection:<entity_id>      # extracted assessment without a history record
assertion_only:<assessment_id>     # no materialized owner yet; value derived from assertions
```

The `owner_locator` is stable for the life of the assessment. It is stored in
the resolved assessment view, not in a second editable file.

### Deadline

A `Deadline` may exist for non-assessment dates such as a course meeting or a
standalone institutional date. For an assessment:

- the due date is the assessment's `due_date`;
- a `deadline` entity in `domain.json` that matches an assessment is a
  **projection alias** (`projection_of: assessment:<id>`), not an owner;
- a ChangeSet updates the assessment owner, then updates or verifies the
  projection alias;
- the two are never independently editable.

If a legacy deadline projection disagrees with its assessment owner, the
assessment wins for the effective value and the disagreement is surfaced as a
conflict. Migration does not delete either record.

### Identity resolution

Assessments are resolved by:

1. exact assessment ID (`assessment:history:<id>`, `assessment:domain:<id>`);
2. exact underlying record ID;
3. exact normalized title within one course, if unique;
4. exact course code/name plus exact normalized title, if unique.

Ambiguous or unknown identifiers fail with a structured error. They never fall
back to a workspace-wide match.

A domain assignment is aliased to a history record only when exactly one history
record in the same course has the same normalized title. If multiple records
match, both remain separate and the view reports an ambiguity warning. No silent
merge.

## Effective value resolution

Every resolved field returns:

```json
{
  "value": "2026-11-20",
  "resolution": "recorded | derived | conflict | needs_confirmation | missing | inconsistent",
  "confidence": "current-confirmed | likely | unverified | historical",
  "verification": "verified | corroborated | unverified | disputed",
  "owner": {"kind": "assignment_history", "locator": "..."},
  "source_kind": "legacy_record | student_report | original_document | ...",
  "evidence": [],
  "alternatives": [],
  "conflicts": [],
  "warnings": []
}
```

### With a materialized owner

If the owner record has a value:

1. The owner value is the effective value.
2. An active assertion that agrees adds corroboration and evidence.
3. An active assertion that disagrees is preserved as an alternative and a
   conflict. It does not silently replace the owner.
4. An assertion marked `applied` whose value no longer matches the owner is an
   `inconsistent` state. The owner value is still returned, but the consumer
   must not treat the record as verified.
5. If the owner's source hash no longer matches the evidence that was indexed,
   the value is returned with a `stale_source` warning.

### Without a materialized owner

If the assessment is `assertion_only`:

1. Filter assertions to active records whose `authority_scope` includes the
   requested field.
2. Apply the field policy (see below) to identify the leading candidate.
3. If one candidate clearly leads, return it as `derived` with its confidence
   and verification.
4. If two candidates cannot be separated safely, return the leading candidate
   with `resolution: needs_confirmation` and list all alternatives. Consumers
   must present it as uncertain.
5. If no candidate exists, return `value: null`, `resolution: missing`.

The effective value is never written back into an assertion as a new assertion.
It is computed on read.

### Field policy

There is no single global hierarchy such as “official > student > AI.” Policy is
field-specific. For `assessment.due_date`, the resolver uses these ordered rules:

1. **Scope must match.** An assertion whose `authority_scope` does not include
   `assessment.due_date` is not a candidate for this field.
2. **Owner record wins when present.** Approval is required to change it.
3. **Verification before recency.** A verified assertion outranks an unverified
   one; corroborated outranks unverified.
4. **Source authority for dates.** A professor announcement or verified external
   source outranks an original syllabus for a changed date; the syllabus remains
   authoritative for its published version. A student report is current but
   unverified. AI extraction points to evidence and never outranks a human
   source or an original document by itself.
5. **Specificity.** An exact date outranks an approximate or partial date.
6. **Recency within the same authority and verification.** A newer assertion
   wins only after the earlier rules tie.
7. **Disagreement is preserved.** If the rules cannot separate two candidates,
   the result is `needs_confirmation`.

The policy is implemented as an explicit tuple comparator per field, not as one
opaque score. This makes the reason for a resolution explainable.

### Verification vs. approval

These are separate:

- **Approval** means the student authorized a ChangeSet operation.
- **Verification** means the fact was independently checked against a source.

Approving a student-reported deadline does not make it verified. The resolved
value remains `student-reported, unverified` until a source verifies it or the
student explicitly confirms the fact separately. A ChangeSet approval is not a
verification signal.

## Legacy migration provenance

Migration must not assign unsupported confirmation.

- Existing records keep their original `record_basis`, actor, timestamps, and
  source path.
- A legacy record becomes an assertion with
  `source_kind: legacy_record`, `verification: unverified`, and a confidence
  derived from its existing metadata, not from the migration.
- If the legacy record already says `record_basis: user-confirmed`, that fact is
  preserved as `legacy.record_basis` for history. It is **not** converted into
  `verification: verified` and is not presented as newly confirmed.
- Migration never changes a deadline, status, grade, or task value.
- Migration never infers a task↔assessment link from matching dates or titles.
  Links require an explicit student action.
- Migration is idempotent and records source hashes so later external edits can
  be detected.

## Storage layout

```text
<academic_root>/.academia/knowledge/
  schema.json
    schema_version
    field_policies
    migration (source hashes, timestamps, warnings)

  assertions.json
    schema_version
    assertions[]
    evidence[]

  links.json
    schema_version
    task_links[]

  change_journal.json
    schema_version
    changesets[]
    events[]
```

`assertions.json`, `links.json`, and `change_journal.json` are durable workflow
state, not caches. They are written atomically with `JsonStateStore` and are
included in backups. They must never be treated as a replacement for the
human-readable academic files.

## External edits

If a canonical file changes outside the engine:

- reads compare the current record revision to the indexed revision;
- a mismatch produces `unindexed_external_change` and `stale_source` warnings;
- the engine does not silently rewrite the file or create a new assertion;
- an explicit re-index operation may append a new legacy assertion with
  `source_kind: external_edit`, preserving the previous assertion.

## Related decisions

- [02-knowledge-model.md](02-knowledge-model.md) defines assertion fields and
  the read contract.
- [03-change-coordination.md](03-change-coordination.md) defines how an approved
  change updates the owner record.
- [05-migration-and-compatibility.md](05-migration-and-compatibility.md) defines
  the migration sequence.
