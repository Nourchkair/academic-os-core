# Phase 4 — Proactive planning and source confidence

Status: **implementation on `next/phase4-proactive`; not merged, tagged, or released**

Phase 1 added the academic knowledge engine and ChangeSet path. Phase 2 added
intake. Phase 3 organized the dashboard into Home, Courses, Planner, and Agent.
Phase 4 makes the workspace work ahead of the student:

> Surface a deterministic daily brief, turn recorded workload into concrete
> study blocks, and make source coverage and verification visible without
> creating another academic store.

## Scope

### 4.1 Daily brief

A local, read-only `academia brief` payload composed from existing services:

- next deadlines and open tasks for the next seven days;
- open Review decisions, pending intake, and processing attention;
- due study reviews and upcoming exams;
- source coverage warnings, stale sources, and unverified readings;
- an advisory study plan for the day;
- a cursor and generated timestamp for external-agent delivery.

The brief is deterministic. It does not call a model, create a schedule, or write
academic state. It is displayed on Home and Planner and is also available to an
external agent through the CLI.

### 4.2 Study blocks and calendar proposals

`academia study schedule` turns the existing advisory `study plan` into concrete
time blocks:

- placement inside student-selected daily hours;
- existing Google Calendar events are treated as busy time when the connector is
  authorized;
- a block is advisory until the student approves a Google Calendar Review
  proposal;
- duplicate checks, approval, separate execution, and read-back verification
  remain unchanged.

The dashboard Planner shows the week's blocks and offers **Add to Calendar** per
block. Nothing is written to Google before Review approval and execution.

### 4.3 Source intelligence

`academia sources health` joins existing stores without adding a parallel one:

- assigned readings from the domain projection;
- matching Library files, processing/extraction state, and file hashes;
- student-reported reading status in the course `study.json`;
- exam scopes and their source/topic coverage;
- syllabus source hashes compared with domain evidence;
- pending intake candidates for announcements;
- unverified and stale sources.

Reading status is student-owned and stored in `study.json`. It is never inferred
from a page view or a model answer.

`academia sources sync` previews an existing Library syllabus through the same
extraction and reconciliation engine; `--apply` adds safe projections and
creates Review items for conflicts. It never rewrites the source. Announcement
sync continues through the existing intake path; source health reports pending
candidates rather than creating a second announcement store.

`academia sources verify-reading` compares requested and retrieved metadata with
the existing `verify_source_metadata` contract, then creates a linked
`domain_change` Review proposal. Approval and execution use the existing
two-stage path; the reading's `verification_result` changes only after verified
execution.

## Non-goals

- A background scheduler, daemon, or automatic calendar write.
- Automatic study-block placement without student review.
- A second reading, exam, or source database.
- Automatic submission, messaging, portal access, or browser scraping.
- Treating a metadata match as proof that a source's content is correct.
- Replacing the Phase 1 ChangeSet engine or Phase 2 intake path.
- A release, version bump, or signed build.

## Safety boundaries

- The brief is advisory and derived from recorded data. It does not manufacture
  urgency or claim that every requirement is known.
- Study blocks are suggestions. Calendar events are created only through a
  Review proposal, explicit approval, a separate execution step, duplicate
  checks, and read-back verification.
- Reading status is `student-reported`; a missing record means unknown, not
  unread.
- Verification compares metadata only. `EXACT MATCH — HIGH CONFIDENCE` is a
  metadata result, not a semantic guarantee.
- No agent may approve its own proposal.
- The browser dashboard may read `sources health`; syllabus apply and reading-verification proposals remain explicit CLI user actions.

## Validation

- Python tests for brief composition, schedule placement/conflicts, source
  health, reading status, syllabus sync preview, verification proposals, and CLI
  contracts: 666 tests pass.
- Frontend typecheck, 66 tests across 22 files, and production build.
- Component tests for the daily brief, study-block planner, source-health panel,
  and the typed calendar Review card.
- CLI and dashboard-transport smoke tests on a copied three-course workspace:
  `brief`, `sources health`, `study schedule`, `study reading`, and
  `sources verify-reading`.
- CI runs the full Python matrix, frontend tests/build, and Tauri Rust compile.

## Implemented slice

```bash
academia brief --semester "Fall 2026" --days 7 --json
academia sources health --semester "Fall 2026" --json
academia sources health --semester "Fall 2026" --course "POL 2103 - Politics" --json
academia sources sync --course "POL 2103 - Politics" --source "Fall 2026/POL 2103 - Politics/01_COURSE/syllabus.pdf" --json
academia sources sync --course "POL 2103 - Politics" --source "Fall 2026/POL 2103 - Politics/01_COURSE/syllabus.pdf" --verified-current --apply --json
academia sources verify-reading --course "POL 2103 - Politics" --reading READING_ID --requested requested.json --retrieved retrieved.json --json
academia study schedule --semester "Fall 2026" --minutes 120 --days 7 --json
academia study reading --course "POL 2103 - Politics" --reading READING_ID --status read --json
```

The dashboard adds:

- a **Today’s brief** section on Home and Planner;
- a **Study blocks** planner on Planner with per-block **Add to Calendar** Review proposals;
- a typed **Calendar change** approval card that shows the event title, time, duplicate check, and effects;
- a **Readings** tab in Courses → Study with reading coverage, student status controls, exam coverage, and syllabus/announcement sync status;
- exam-scope source selection and source availability in the existing Exam scope coverage panel.
