# 05 — Migration and backward compatibility

Status: **frozen for Phase 1**

## Decision

Migration is additive. It creates the knowledge store and links to existing
records. It does not rewrite canonical academic files and does not assign
confirmation that the original data did not have.

## Migration inputs

For the selected semester:

```text
SEMESTER/SEMESTER_TASKS.md
SEMESTER/COURSE/03_ASSIGNMENTS/Assignment_History.json
.academia/domain.json
SEMESTER/COURSE/06_KNOWLEDGE/STUDY/study.json   # read-only inventory
```

Original course documents remain untouched and are referenced by evidence.

## Migration sequence

1. **Backup first.** The existing backup path remains mandatory. A migration run
   on a copy is the default in tests and is recommended for first use.
2. **Inventory.** Read each canonical record and compute a stable content hash.
3. **Build assessments.**
   - Every history record becomes an assessment with
     `owner_kind: assignment_history`.
   - Every domain assignment without a unique history match becomes an
     assessment with `owner_kind: domain_projection`.
   - A domain assignment that uniquely matches a history record is recorded as a
     projection alias. It does not become a second assessment.
   - Ambiguous matches remain separate and produce a warning.
4. **Link deadline projections.**
   - A domain deadline that matches an assessment is recorded as a projection
     alias of that assessment.
   - A domain deadline that does not match an assessment remains a standalone
     deadline with `owner_kind: domain_projection`.
   - No deadline is deleted.
5. **Append legacy assertions.**
   - One assertion per indexed field (at minimum assessment `due_date`, where
     present).
   - `source_kind: legacy_record`.
   - `verification: unverified`.
   - `confidence` is derived from existing metadata, capped at `historical` or
     `likely`; it is never upgraded to `current-confirmed` by migration.
   - The original `record_basis`, actor, timestamps, and source path are
     preserved under `legacy` metadata.
6. **Do not infer links.** Existing `task_title` values and matching dates are
   not links. A task link requires an explicit student action.
7. **Do not migrate study records into assertions.** `study.json` is canonical
   for study data. Its exam scope is not an assessment deadline.
8. **Record migration metadata.**
   - migration ID, timestamp, semester, source hashes, warnings;
   - idempotency key per source record;
   - a readable summary in `.academia/knowledge/schema.json`.
9. **Verify.** Re-read every source hash and confirm no canonical file changed
   during migration.

## Legacy provenance rules

| Legacy value | Migrated assertion |
| --- | --- |
| Record has `record_basis: user-confirmed` | `source_kind: legacy_record`, `verification: unverified`, `legacy.record_basis: user-confirmed` |
| Record has a grade or status | Same value; no new confirmation |
| Domain entity from extracted syllabus | `source_kind: legacy_record` or `ai_extraction` if the extraction provenance is known; `verification: unverified` |
| Missing deadline | No assertion; field remains `missing` |
| Conflicting history and domain values | Both preserved; history owner wins for the effective value; conflict is reported |

The phrase “user-confirmed” in an old file describes how that file was recorded.
It is not promoted to a new verification claim.

## Idempotency

- Each migrated record has a deterministic migration key:
  `sha256(semester + owner_kind + owner_id + field + value_hash)`.
- Re-running migration skips an existing key.
- Re-running migration after a canonical file changes appends a new
  `external_edit` assertion; it does not overwrite the old one.
- A migration run never creates duplicate links or duplicate assessments.

## External edits after migration

If `Assignment_History.json`, `SEMESTER_TASKS.md`, or `domain.json` changes
outside the engine:

- the next read detects a hash mismatch and reports
  `unindexed_external_change`;
- the canonical value still wins for the read;
- the engine does not silently create a verified assertion;
- an explicit `knowledge migrate --refresh` may append an `external_edit`
  assertion and update the index;
- a pending ChangeSet whose `expected_revision` no longer matches is blocked
  until re-proposed.

## Compatibility

- Existing CLI commands and JSON shapes remain unchanged.
- Existing `domain.json`, `Assignment_History.json`, `SEMESTER_TASKS.md`, and
  `study.json` remain readable without the knowledge engine.
- The new engine is additive: if `.academia/knowledge/` is absent, existing
  features behave exactly as before.
- The new UI entry point is explicit. It does not replace the existing History
  editor or task editor.
- Existing Review/Action flows remain in place. A ChangeSet is a new,
  structured proposal path for the deadline slice; it does not delete or
  rewrite old Review items.
- Existing MCP tools are unchanged. Phase 1 does not add agent approval tools.
- Backup and restore include `.academia/knowledge/`.
- No schema version of an existing file is bumped by Phase 1.

## Rollback

- Cancelling a ChangeSet before execution leaves canonical files untouched.
- Reversing an executed ChangeSet uses the conditional reversal contract.
- Disabling the new UI or commands leaves the knowledge store inert; canonical
  files remain usable.
- A migration failure leaves the original files untouched and reports the
  failure. It does not partially rewrite canonical records.
- Restoring a backup restores the knowledge store with the workspace.

## Data safety

- No migration step writes to a course source document.
- No migration step deletes an assertion, task, history record, or domain
  entity.
- No migration step marks a record as verified.
- No migration step contacts an external service.
- No migration step reads credentials or browser sessions.

## Acceptance

Migration is complete only when:

- a fresh workspace and a legacy workspace both open;
- existing records keep their values and provenance;
- re-running migration is idempotent;
- a simulated external edit is detected, not overwritten;
- a conflicting history/domain deadline is visible, not merged silently;
- no task link is inferred;
- backup/restore includes the knowledge store.

## Related contracts

- [01-sources-of-truth.md](01-sources-of-truth.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
- [09-phase1-plan.md](09-phase1-plan.md)
