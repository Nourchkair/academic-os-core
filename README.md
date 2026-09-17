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
  --timezone America/Toronto --semester "Fall 2026" --json
academia --profile ~/.academic-os/profile.json workspace attach /path/to/University \
  --name "Your name" --institution "Your university" --program "Your program" \
  --timezone America/Toronto --semester "Fall 2026" --apply --json
```

`workspace inspect` is read-only. `workspace attach` is preview-only unless `--apply` is supplied; attachment writes only the local profile and does not migrate, rename, move, rewrite, or index academic files. Generated profiles use schema version 2, resolve a real semester label, keep browser access off by default, and do not require Hermes. Existing schema-version-1 profiles migrate non-destructively when read.

## Universal local interface

Agents should request structured context through the CLI rather than parsing dozens of Markdown files:

```bash
academia status --json
academia workspace --json
academia workspace discover --json
academia workspace inspect /path/to/University --json
academia workspace create /path/to/New\ University --name "Your name" --institution "Your university" --timezone America/Toronto --semester "Fall 2026" --apply --json
academia courses --json
academia course "POL 2103 - Politics" --json
academia today --json
academia tasks --json
academia review --json
academia inbox --json
academia activity --json
academia agents --json
academia capabilities --json
academia import /path/to/file.pdf --destination /path/to/workspace/Fall\ 2026/COURSE/00_INBOX --json
academia import /path/to/unknown-file.pdf --destination /path/to/workspace/Fall\ 2026/00_INBOX --uncertain --json
academia watch --json  # one-shot scan of configured folders
```

Use `--profile /path/to/profile.json` when the profile is not at `~/.academic-os/profile.json`.

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

1. **Manual import** — `academia import SOURCE --destination INBOX` copies a user-selected PDF, DOCX, PPTX, text, HTML, or other normal academic file into a workspace inbox; the original remains in place and the copy enters intake.
2. **Watched folders** — `academia watch` performs a one-shot scan of configured local directories such as `Downloads/School`. A persistent background watcher is not claimed yet.
3. **Browser companion** — architecture only for now. A future companion will support explicit actions such as “Send to Academia OS,” “Save reading,” and “Import this page.”
4. **Advanced browser access** — optional and off by default.

The current capability report is honest: manual import and one-shot watched-folder scanning are available; Chromium is limited to optional visible handoff with an explicit allow-list and target; Firefox and Safari are planned, not claimed as connected. The user may choose Chrome, Firefox, Safari, or another profile. A dedicated school/research profile is recommended for privacy but not required. Domain allow-lists narrow intended access but are not a security guarantee.

For readings, prefer legitimate library, Omni/OpenAthens, publisher, DOI/open-access, institutional, or author-released access. Discovery-only sources do not authorize downloading an unclear copy. Never pay without explicit confirmation, and never silently substitute an edition.

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

It is a React + TypeScript application with a Tauri 2 shell and a typed bridge to the `academia` CLI. It now includes profile-free first-run onboarding, existing-workspace inspection/attachment, fresh-workspace setup, Home, Courses, Tasks, Library, Import, Review, and Settings views with local-data/error/empty states. Import uses the native Tauri file picker and drag/drop paths but delegates copying, processing, provenance, Activity, and uncertainty Review items to the existing CLI/core. The Tauri bundle is currently a development foundation (`bundle.active` is false); macOS signing, notarization, and sidecar packaging remain release work. The old Tkinter app remains as a compatibility fallback while the new shell matures.

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
