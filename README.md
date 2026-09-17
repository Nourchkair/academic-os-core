# Academia OS

Academia OS is a local-first academic operating system for a student’s computer. It organizes a human-readable University workspace, keeps provenance and uncertainty visible, provides a durable review/activity model, and exposes a stable local CLI/API contract for any authorized agent.

It is **not** a Hermes product. Hermes is one optional adapter. Academia OS works without Hermes, Codex, ChatGPT/Work, Claude, browser automation, or a school account connection.

## What changed in the agent-neutral architecture

```text
Hermes / Codex / ChatGPT / Claude / future agents
                         │ optional adapters
                         ▼
              Academia OS interface (CLI / Tauri bridge)
                         │
                         ▼
              academia_os core and local workspace
              ├── human-readable files
              ├── .academia indexes/state
              └── proposals → approval → execute → verify → activity
```

The core owns configuration, workspace discovery, semesters, courses, sources, provenance, source verification, review items, activity, processing state, migration, acquisition metadata, and action policy. It does not import Hermes.

## Install the core locally

Requirements: Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
academia --help
```

The first-use experience is available in the modern Tauri frontend as well as through the compatibility installer. The desktop flow checks for an existing profile; if it is missing, stale, invalid, or points at a missing/unrecognized workspace, it opens onboarding instead of silently using test data.

The compatibility installer remains available for scripted/bootstrap environments:

```bash
python -m installer.bootstrap --manifest config/manifest.example.json
```

The modern setup flow can:

- create a fresh workspace through the existing installer/template service;
- inspect an existing Academia-style folder without creating `.academia/` or changing academic files;
- show semesters, courses, file counts, markers, and structure anomalies;
- preview the profile attachment before confirmation; and
- back up an existing local profile before replacing it.

For a profile-free inspection or attachment preview:

```bash
academia workspace discover --json
academia workspace inspect /path/to/University --json
academia --profile ~/.academic-os/profile.json workspace attach /path/to/University \
  --name "Your name" --institution "Your university" --program "Your program" \
  --timezone America/Toronto --json
academia --profile ~/.academic-os/profile.json workspace attach /path/to/University \
  --name "Your name" --institution "Your university" --program "Your program" \
  --timezone America/Toronto --apply --json
```

`workspace inspect` is read-only. `workspace attach` is preview-only unless `--apply` is supplied; attachment writes only the local profile and does not migrate, rename, move, rewrite, or index academic files. Generated profiles use schema version 2, resolve a real semester label, keep browser access off by default, and do not require Hermes. Existing schema-version-1 profiles migrate non-destructively when read.

## Universal local interface

Agents should request structured context through the CLI rather than parsing dozens of Markdown files:

```bash
academia status --json
academia workspace --json
academia workspace discover --json
academia workspace inspect /path/to/University --json
academia semester --timezone America/Toronto --json
academia workspace create /path/to/New\ University --name "Your name" --institution "Your university" --timezone America/Toronto --apply --json
academia courses --json
academia course "POL 2103 - Politics" --json
academia today --json
academia tasks --json
academia review --json
academia review decide REVIEW_ID use_new --json
academia review execute REVIEW_ID --json
academia domain --json
academia extract syllabus /path/to/syllabus.pdf --course "POL 2103 - Politics" --json
academia extract syllabus /path/to/syllabus.md --course "POL 2103 - Politics" --verified-current --apply --json
academia settings show --json
academia settings update --set student.name="Student" --json
academia inbox --json
academia activity --json
academia agents --json
academia capabilities --json
academia import /path/to/file.pdf --destination /path/to/workspace/Fall\ 2026/COURSE/00_INBOX --json
academia import /path/to/unknown-file.pdf --destination /path/to/workspace/Fall\ 2026/00_INBOX --uncertain --json
academia watch --json  # one-shot scan of configured folders
```

Use `--profile /path/to/profile.json` when the profile is not at `~/.academic-os/profile.json`.

### Browser dashboard

Build the frontend first, then start the local-only browser dashboard. The shortest command opens it directly:

```bash
cd frontend
npm install
npm run build
cd ..
academia
```

The explicit equivalent is:

```bash
academia dashboard
```

Both commands start the local server and open the dashboard in the default browser. To start the server without opening a browser—for example, from a script or while using a different browser—use:

```bash
academia dashboard --no-open
```

The dashboard transport binds to loopback only (`127.0.0.1` by default); it has no authentication, cookies, or remote-network access. It serves the built `frontend/dist` files and delegates browser commands to the existing JSON CLI. In browser mode, the Import view uses a native file input or drag/drop and streams the selected bytes to the same local server only; the server stages them temporarily, imports them through the normal copy-first import path, records `browser-upload:<filename>` provenance, and removes the temporary staging file. Native Tauri file and folder pickers remain available in the packaged/development shell. For live frontend development, keep `academia dashboard --no-open` running and use `npm run dev` in another terminal; Vite proxies `/api` to the local dashboard.

Settings use a preview/apply model:

```bash
academia settings show --json
academia settings update --set student.name="New name" --json
academia settings update --set student.name="New name" --apply --json
```

Workspace root, runtime directory, and semester changes require `--approve-structural` and are never silently rebuilt or moved.

## Workspace and readable files

The configured academic root remains the source of truth for the user. It contains semesters, course folders, Markdown status files, readings, notes, and imported material. `.academia/` stores rebuildable `index.json`, processing records, review items, activity events, and action proposals. Processing state is canonical under `<academic-root>/.academia/`; the runtime directory does not contain a second operational queue. A user can inspect and use the workspace without Academia OS.

The processing lifecycle is explicit:

```text
DETECTED → PENDING → PROCESSING → VERIFIED → ACKNOWLEDGED
                                  └→ FAILED → retry → PENDING
```

A scan never acknowledges work. Stale processing leases return to retryable state. Only verified work can be acknowledged.

## Import and acquisition

Academia OS remains useful with no browser access:

1. **Manual import** — `academia import SOURCE --destination DESTINATION` copies a user-selected local file; the original remains in place and the copy enters intake. The reusable core accepts only these destination shapes:
   - `<workspace>/<recognized-semester>/00_INBOX/` when the course is unknown.
   - `<workspace>/<recognized-semester>/<recognized-course>/00_INBOX/` when the course is known.
   The semester must be an existing recognized semester directory. The course must be an existing direct course directory belonging to that semester. Nested paths such as `COURSE/03_ASSIGNMENTS/00_INBOX`, arbitrary folders, the workspace root, paths outside the workspace, and `.academia/` are rejected. Fresh workspaces create the semester-level `00_INBOX/`; older workspaces remain readable and receive it only when explicitly initialized/used.
2. **Watched folders** — `academia watch` performs a one-shot scan of configured local directories such as `Downloads/School`. A persistent background watcher is not claimed yet.
3. **Browser companion** — architecture only for now. A future companion will support explicit actions such as “Send to Academia OS,” “Save reading,” and “Import this page.”
4. **Advanced browser access** — optional and off by default.

The current capability report is honest: manual import and one-shot watched-folder scanning are available; Chromium is limited to optional visible handoff with an explicit allow-list and target; Firefox and Safari are planned, not claimed as connected. The user may choose Chrome, Firefox, Safari, or another profile. A dedicated school/research profile is recommended for privacy but not required. Domain allow-lists narrow intended access but are not a security guarantee.

For readings, prefer legitimate library, Omni/OpenAthens, publisher, DOI/open-access, institutional, or author-released access. Discovery-only sources do not authorize downloading an unclear copy. Never pay without explicit confirmation, and never silently substitute an edition.

### Legacy-folder migration

A fresh workspace can be populated from an older, messy university folder without changing the original by default. The migration surface is neutral and can be used by the CLI, the React/Tauri app, or an authorized agent:

```bash
academia migration plan /path/to/old-university-folder --json
academia migration status --plan ~/.academic-os/migration/migration-plan.json --json
academia migration execute --plan ~/.academic-os/migration/migration-plan.json --item 0 --item 3 --mode copy --apply --json
# Destructive mode requires both flags and should be used only after explicit review:
academia migration execute --plan ~/.academic-os/migration/migration-plan.json --mode move --confirm-move --apply --json
```

The plan is read-only and records each source hash, proposed semester-aware destination, and review artifact. Current-semester or unknown material is routed to `00_INBOX/LEGACY_IMPORT`; older semesters are routed to `99_ARCHIVE/LEGACY_IMPORT`. Files can be selected individually, copied by default, or left untouched by clearing the selection. Existing destinations are never overwritten. Execution rechecks source hashes, verifies destination hashes, records a JSON report, and preserves the old folder for copy mode. Unsafe/operational folders, symlinks, traversal paths, runtime state, and plans outside the active runtime migration directory are rejected. The migration view is available from the modern desktop navigation and from the final onboarding step.

## Derived academic domain projection

`academia domain --json` reads the optional `.academia/domain.json` projection. The projection supports evidence-backed `AcademicSource`, `Deadline`, `Assignment`, `Reading`, `Announcement`, and `CourseMeeting` records. Every record retains source path, provenance, confidence, authority, and verification timestamps. Unknown values remain null. The projection is derived state; human-readable academic files remain authoritative, and this pass does not semantically parse the real University workspace.

## Controlled syllabus extraction

Syllabus extraction is a narrow, local, preview-first pipeline:

```text
local syllabus → SourceDocument/SourceSegment → candidate facts
→ evidence/confidence validation → domain reconciliation → Review/Action
→ approved DOMAIN_CHANGE → reread verification → Activity
```

Use:

```bash
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --json
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --verified-current --apply --json
academia review decide REVIEW_ID use_new --json
academia review execute REVIEW_ID --json
```

Supported source formats are text-based PDF, plain text, and Markdown. Text-based PDFs retain page references; text and Markdown retain line/segment references. Extraction is deterministic and local using the lightweight `pypdf` dependency for PDF text. No syllabus is sent to a model or hosted service. Scanned/image-only PDFs return `unsupported_without_ocr`; OCR is intentionally not part of this pass. Other formats are unsupported by the syllabus extractor, although normal manual import can still preserve them in `00_INBOX/`.

The first syllabus extractor only proposes course identity, assignments, explicit deadlines, assessment weights, required readings, and recurring course meetings. It does not interpret every date, policy, biography, URL, or arbitrary note. Missing dates, years, times, weights, pages, and course identity remain null or produce a warning. `current-confirmed` is used only when the user explicitly marks the supplied syllabus as current; otherwise directly stated facts are `likely` and ambiguous facts are `unverified`.

Preview mode does not write the domain projection, source file, workspace files, Review, Action, calendar, or school account. Apply mode adds safe derived entities and creates typed Review items for conflicts. A changed deadline never silently replaces an existing value: the proposal contains before/after values plus both evidence records. `use_new` approves the exact `DOMAIN_CHANGE`; execution rereads `.academia/domain.json`, verifies every requested field, resolves Review, and records Activity. A failed reread rolls back the derived update where possible, marks the proposal failed, reopens Review, and records the failure.

## Safety and privacy

- Originals are preserved; copies and collision-safe names are preferred.
- Destructive changes require an approved proposal.
- Calendar changes require approval and duplicate checking.
- No academic submission, school-account message, payment, or authentication action is implemented or permitted.
- Passwords, MFA codes, cookies, session tokens, and hidden secrets are not read or stored.
- School/browser access is optional and read-only in the current architecture.
- Local health verification is separate from safe-to-share auditing:

```bash
python -m installer.verify /path/to/profile.json
python -m installer.verify /path/to/profile.json --share-audit /path/to/export
```

An email address or local path can be normal in a private workspace; it should be reported by the share audit, not treated as a broken local installation.

## Review and activity

Uncertain source matches, deadline conflicts, and approval-required changes are durable structured Review items under `.academia/review.json`. Action-linked Review items contain the exact `action_proposal_id`; approving the Review item approves that proposal, and the item resolves only after the proposal is executed and verified. Activity events are append-only JSON lines under `.academia/activity.jsonl`, with human-readable fields such as title, course, source, confidence, authority, and action. The desktop Home/Review views consume these models rather than hardcoded notice text.

## Desktop application

The modern frontend lives under `frontend/`:

```bash
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

It is a React + TypeScript application with a Tauri 2 shell and a typed bridge to the `academia` CLI. It now includes profile-free first-run onboarding, existing-workspace inspection/attachment, fresh-workspace setup, Home, Courses, Tasks, Library, Import, **Migrate older material**, Review, and Settings views with local-data/error/empty states. The migration view scans an explicitly selected legacy folder, previews every destination, supports selected copy by default, and gates destructive Move behind an additional confirmation. Import uses the native Tauri file picker and drag/drop paths but delegates copying, processing, provenance, Activity, and uncertainty Review items to the existing CLI/core. The Tauri bundle is currently a development foundation (`bundle.active` is false); macOS signing, notarization, and sidecar packaging remain release work. The old Tkinter app remains as a compatibility fallback while the new shell matures.

## Optional agents

- `adapters/hermes/` contains optional Hermes detection and job translation.
- Codex, Claude, and ChatGPT/Work are generically compatible through `AGENTS.md` plus the local CLI; dedicated adapters are not required. Hermes remains the only dedicated adapter currently implemented.
- Agents should read `AGENTS.md` and use `academia ... --json`.

## Development and tests

```bash
python3 -m pytest tests/ -q
python3 -m compileall academia_os installer desktop adapters
cd frontend && npm run typecheck && npm run build
```

The canonical Python version is `academia_os/version.py`. The frontend/Tauri package metadata is checked against that value in CI.

## Backward compatibility

The existing installer, migration engine, and Tkinter app remain available. Existing v1 profiles migrate into v2 when loaded; the legacy `hermes` object is retained only as a compatibility alias. New profiles use `runtime`, `agents`, `acquisition`, and `privacy` sections. Migration and imports are copy-first and collision-safe; existing academic files are not silently moved or overwritten.
