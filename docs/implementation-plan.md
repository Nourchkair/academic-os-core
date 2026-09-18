# Academia OS Agent-Neutral Refactor Plan

## Goal

Turn the current Hermes-coupled Python/Tkinter system into a local-first, agent-agnostic academic operating system while preserving the existing academic safety, provenance, non-destructive migration, and read-only school-access principles.

## Current baseline

- Python installer/core, runtime scripts, migration engine, and Tkinter desktop wrapper.
- 22 passing Python tests.
- No supported installable Python package or universal CLI.
- Hermes paths, cron generation, skill installation, and inbox state are embedded in core/runtime behavior.
- Config schema and Python validation can drift.
- Inbox gate persists signatures before downstream processing succeeds.
- No structured persisted Review Queue or Activity model.
- No React/TypeScript/Tauri foundation.

## Current implementation status

The original architecture/refactor slices are implemented and verified. The current product pass adds the student-facing bridge without creating parallel core systems:

- **Existing-workspace attachment:** `academia workspace discover` and `workspace inspect PATH` are profile-free and read-only. `workspace attach` previews the filesystem projection and writes only a local profile after `--apply`; stale/invalid test profiles are backed up first.
- **Fresh-workspace setup:** `workspace create PATH` previews the existing installer/template plan and invokes `installer.core.initialize_installation` only after `--apply`.
- **Modern onboarding:** the React/Tauri shell now detects missing/stale/unrecognized setup and guides Welcome → Profile → Workspace → Semester → Sources → Interface note → Review → Ready.
- **Modern import:** the frontend uses the native Tauri dialog and Tauri drag/drop paths, while every copy still goes through the existing `academia import` command. “Not sure where this belongs” stages general intake and creates a durable `import_classification` Review item.
- **Typed Review:** deadline conflicts, source/reading verification, imported-file classification, course uncertainty, and action approval now render as decision-specific cards and persist choices through `review decide`.
- **Functional Settings:** one local setup section now groups Profile, Workspace, and Sources & Imports. AI/agent connections, browser sessions, and automation schedules are intentionally not Settings controls because they are owned outside Academia OS; Advanced only shows local technical paths/version. Structural changes still show before/after and require explicit approval.
- **Domain foundation:** evidence-backed `AcademicSource`, `Deadline`, `Assignment`, `Reading`, `Announcement`, and `CourseMeeting` projections persist under `.academia/domain.json`; no real-workspace semantic extraction is performed.
- **Controlled syllabus extraction:** local text/Markdown/text-PDF extraction produces page/line-referenced candidates for course identity, assignments, explicit deadlines, weights, readings, and recurring meetings. Preview is side-effect free; apply reconciles idempotently, creates typed deadline conflicts, and exposes verified `DOMAIN_CHANGE` execution through the existing Review → Action → Verification → Activity workflow.
- **Still intentionally incomplete:** OCR, arbitrary-document semantic extraction, persistent background watchers, external source retrieval, execution of every possible action type, bundled sidecar packaging, signing, and notarization.

The live user workspace is never a repository fixture. Product tests use temporary sanitized workspaces only.

## Architecture target

```text
agents/
  Hermes / Codex / Claude / ChatGPT / future adapters
          |
adapters/  (optional integrations; no core dependency)
          |
interface/
  academia CLI + stable JSON contracts + future Tauri commands
          |
core/
  config, workspace, semester, provenance, sources, tasks,
  review, activity, actions, acquisition, processing lifecycle
          |
workspace files + rebuildable .academia/ state/index
```

## Execution slices

### Slice 1 — Read-only contracts and canonical core

- Add `academia_os/` package with public domain/service modules.
- Add one canonical config model/schema version with explicit migration support.
- Keep loading schema-version-1 profiles and migrate them forward non-destructively.
- Add semester resolution based on date and configurable academic calendar policy; prohibit persisting the literal `Current Semester`.
- Add normalized models for Workspace, Semester, Course, AcademicSource, Task, ReviewItem, ActivityEvent, AcquisitionSource, ActionProposal, and processing records.
- Add append-only activity persistence, structured review queue persistence, and rebuildable `.academia/index.json`/state files.
- Add focused tests before implementation for schema migration, semester resolution, review/activity persistence, provenance, and path safety.

### Slice 2 — Hermes adapter extraction

- Move Hermes-specific cron/skill/state/environment behavior under `adapters/hermes/`.
- Make the core installer able to create a complete workspace/runtime without Hermes installed.
- Make Hermes detection optional and report capability states instead of requiring it.
- Preserve existing Hermes scripts as adapter resources and compatibility wrappers.
- Namespaces adapter state by installation identity/profile.

### Slice 3 — Universal interface

- Add `academia` console entry point and `academia_os.cli`.
- Implement stable human/JSON commands for status, workspace, courses, course, today, tasks, review, inbox, activity, verify, settings, import, and watched folders.
- Use structured errors and non-zero exit codes.
- Keep `desktop/app.py --print-dashboard` and old installer entry points as compatibility facades over the new services.

### Slice 4 — Reliable processing and acquisition foundations

- Replace signature-only inbox gate with persistent lifecycle records:
  `DETECTED -> PENDING -> PROCESSING -> VERIFIED -> ACKNOWLEDGED`, with `FAILED` retryable.
- Add lease expiry/stale-processing recovery, retry count, timestamps, failure reason, source hash, and acknowledgment metadata.
- Only successful verification may acknowledge work.
- Add normalized manual import, watched-folder, and browser-companion capability contracts.
- Keep browser automation optional and default OFF; expose Chromium as the only implemented browser automation adapter, with Firefox/Safari/companion marked planned/unsupported honestly.
- Preserve read-only school acquisition and source legality/version-verification rules.

### Slice 5 — Settings and product state

- Load existing configuration into the settings UI/service.
- Implement non-destructive config updates with diff/impact summary and explicit approval for workspace/structural changes.
- Add structured task/current-state projections, Review Queue, Activity, and source/index views.
- Keep Markdown files human-readable; `.academia/` stores rebuildable indexes, lifecycle state, reviews, activities, and config metadata.

### Slice 6 — Modern frontend foundation

- Add a React + TypeScript frontend with a polished Home/semester-scoped Courses/Tasks/Activity/Settings shell; Courses owns the academic library browser and external-agent Review records are not presented as a built-in queue.
- Add a reproducible Vite build and typed interface client against the CLI/service contract.
- Add structured empty/loading/error states and accessibility foundations.
- Add a Tauri-ready `src-tauri` boundary only where the local environment supports it; do not claim native packaging/signing if Rust/Tauri are unavailable.
- Keep Tkinter as a compatibility fallback until parity is proven.

### Slice 7 — Documentation, CI, and release hygiene

- Add generic `AGENTS.md` at repository/workspace level.
- Move Hermes instructions to `adapters/hermes/` and document future adapter locations without pretending support exists.
- Update README/architecture/security/acquisition/browser/privacy/settings/review/activity docs.
- Add canonical version source and version checks.
- Fix `pyproject.toml` packaging/console script and add frontend lock/build metadata.
- Expand CI for Python, schema, CLI, frontend, and macOS-specific checks that are actually available.

## Compatibility and safety rules

- Existing user files and course content are never overwritten or deleted by migration/refactor.
- Existing schema-version-1 profiles remain readable through migration.
- Hermes remains usable when detected but is never required for core installation or CLI operation.
- No academic submission, school-account message, payment, or destructive action is implemented.
- Browser access remains opt-in and allowlist-oriented; manual import and watched folders work without browser access.
- Unsupported integrations are represented as unavailable/planned, not connected.

## Verification plan

- Focused unit tests per slice, written first and observed failing where new behavior is introduced.
- Full Python tests and compile checks.
- CLI subprocess tests for human and JSON outputs/errors.
- Temporary workspace end-to-end bootstrap/settings/migration/review/activity/retry tests.
- Frontend typecheck/lint/build and component/contract tests.
- macOS app/core smoke checks available on the host; document signing/notarization as external release work.
- Diff/secret/privacy audit and final manual UI inspection of available frontend artifacts.

## Deliberate boundaries

- Do not fabricate full Safari/Firefox automation or ChatGPT/Codex/Claude integrations.
- Do not make AI content interpretation authoritative over source/provenance.
- Do not rewrite stable academic templates into an opaque database.
- Do not remove the Tkinter fallback before the new interface has compatibility coverage.
