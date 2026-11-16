# Phase 0 — Academic knowledge and change-coordination contracts

Status: **implemented and locally validated on `next/academic-engine`; not merged or released**

This directory defines the contracts for the first Academic Intelligence Engine
slice. It is deliberately narrower than the five-phase product roadmap.

The guiding rule:

> Academic intelligence is the product. ChangeSets are one mechanism that makes
> it reliable and actionable.

## What Phase 0 decides

1. Existing academic files remain canonical for their domains.
2. The knowledge layer stores evidence, assertions, relationships, and effective
   value resolution without creating a second mutable copy of the same field.
3. Each assessment has exactly one deadline owner.
4. Assertions are field-level and append-only. Disagreement is preserved.
5. ChangeSets coordinate consequential changes through explicit approval, a
   durable operation journal, verification, partial-failure state, and
   conditional reversal.
6. The first slice is local-only: an assessment deadline change and explicitly
   mirrored task due dates.
7. Agents may propose. Agents may not approve their own proposals.
8. Migration preserves historical provenance and never invents confirmation.

## What Phase 0 does not decide

The engine does not yet model every academic concept, replace Review or Study,
connect Google Calendar, or redesign the workspace. See
[non-goals](07-non-goals.md).

## Contracts

| Document | Contract |
| --- | --- |
| [01-sources-of-truth.md](01-sources-of-truth.md) | Canonical ownership, storage, assessment/deadline ownership, effective values |
| [02-knowledge-model.md](02-knowledge-model.md) | Entities, IDs, relationships, assertions, evidence, resolution, read model |
| [03-change-coordination.md](03-change-coordination.md) | ChangeSet, operations, dependencies, approval, journal, recovery, reversal |
| [04-permissions-and-safety.md](04-permissions-and-safety.md) | Actors, channels, permission matrix, prohibited behavior |
| [05-migration-and-compatibility.md](05-migration-and-compatibility.md) | Legacy mapping, provenance preservation, compatibility, backup |
| [06-ux-contract.md](06-ux-contract.md) | Impact preview, approval, partial failure, reversal, first-slice flow |
| [07-non-goals.md](07-non-goals.md) | Explicit exclusions |
| [08-acceptance-tests.md](08-acceptance-tests.md) | Golden scenarios and required test matrix |
| [09-phase1-plan.md](09-phase1-plan.md) | Implementation breakdown and validation plan |

## First vertical slice

> “My professor moved the Second Essay deadline from November 12 to
> November 20.”

The local flow is:

```text
student report
  → resolve course and assessment
  → record evidence/assertion
  → build a ChangeSet with impact preview
  → student approves all or a subset
  → apply local owner records and explicitly mirrored tasks
  → verify every operation
  → record Activity
  → optionally reverse reversible operations
```

The slice is complete only when the acceptance tests in
[08-acceptance-tests.md](08-acceptance-tests.md) pass, including conflict,
partial-approval, crash-recovery, and reversal-conflict cases.

## Durable state

```text
<academic_root>/.academia/knowledge/
  schema.json           field policies and migration metadata
  assertions.json       append-only assertions and evidence references
  links.json            explicit assessment↔task relationships
  change_journal.json   ChangeSets, operation state, and append-only events
```

These are durable workflow records, not rebuildable indexes. The human-readable
academic workspace remains readable without Academia OS.

## Phase 1 status

The local deadline-change slice is implemented on `next/academic-engine` and
validated with:

- Python knowledge, ChangeSet, migration, recovery, and permission tests;
- frontend typecheck, component tests, and production build;
- a real browser walkthrough on a copied workspace: preview, partial approval,
  skipped mirrored task, paused link, verified result, and conditional reversal;
- an end-to-end dashboard command-bridge walkthrough;
- a read-only check against a real workspace copy.

It is **not merged, released, or installed** into `/Applications/AcademiaOS.app`.
The installed app and the `academia` launcher still use the existing release.
