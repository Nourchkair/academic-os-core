# Academia OS

[Visit the Academia OS website](https://academia-os.nearbykestrel1.chatgpt.site) · [Check GitHub Releases for app downloads](https://github.com/Nourchkair/academic-os-core/releases)

Academia OS is a **local-first academic operating layer** for a student’s computer. It supports external agents such as Codex and Hermes, and its dashboard Study chat currently uses the user's signed-in Codex CLI. Academia OS owns the human-readable workspace, academic state, evidence, provenance, permissions, safe actions, structured Study records, and audit trail. Study chat can create exact personal-task or file-import proposals for Review when the relevant per-tool grant is enabled; it cannot approve or execute them. Settings can start the official Codex ChatGPT device-code sign-in without Academia storing credentials. The in-app chat does not yet call external MCP tools such as browser, Gmail, or calendar.

It is **not** a Hermes product. Hermes is one optional adapter. Academia OS works without Hermes, Codex, ChatGPT/Work, Claude, browser automation, or a school account connection.

> **Status: Early public alpha / pre-1.0.** The current version is `0.4.x`. A signed macOS beta bundle and in-app updater are being prepared; app downloads will appear on GitHub Releases after the release workflow completes. Until then, source-based macOS installation is available. APIs, schemas, and adapter contracts may evolve before 1.0. Academic data remains local to the student's computer.

## Shared core, multiple assistant hosts

```text
Academia Assistant (target host)    Codex / Claude / other external host
provider choice · MCP client         provider and tool environment
                  \                       /
                   \                     /
                    ▼                   ▼
                 shared local Academia interface
        context · evidence · provenance · Review · safe actions
                         │
                         ▼
              human-readable academic workspace
        originals · student material · structured Study records

Dashboard: observability · browsing · status · Activity · settings
```

The shared core composes workspace, courses, tasks, Library, domain projections, Review, Activity, processing, provenance, capabilities, and student workflow preferences into bounded `academia agent ... --json` and `academia workflow ... --json` views. It does not create a second academic database. External agent conversations are not stored by the core; dashboard Study chat history is kept separately in browser storage. The Study chat uses the installed Codex CLI sign-in. Claude subscription routing is disabled in Academia because Anthropic restricts subscription OAuth to Claude Code and other native Anthropic apps; Claude Code remains usable as a separate external agent. Academia does not read or store provider credentials. MCP client connections to external services remain future work. See [the assistant architecture and delivery stages](docs/assistant-architecture.md).

## Study with your agent or the dashboard

Each course now has a shared study workspace for cited quizzes, written practice, flashcards, mind maps, explanations, saved attempts, review schedules, annotations, exam preparation and time-bounded study plans. Ask your authorized agent to study with you using `academia study`; the same sets and sessions are available in Courses → Study. Dashboard Study chat currently uses Codex with the user's ChatGPT plan sign-in, with model, reasoning effort, selected course excerpts, document attachments, and PDF text extraction. Codex also supports image attachments and Fast mode. Proposal mode can prepare exact personal-task or file-import Review items, with separate grants for each tool; browser runs stream progress, support Stop, show live Review status, and let you edit a task proposal before approving it. The assistant cannot approve or execute proposals. Settings offers an app-level ChatGPT device-code sign-in through Codex's official flow; Academia never stores your credentials. Chat history persists in browser storage on the current device; attachments are not saved. Study material can be generated through Codex or a loopback local model. Claude Code can still connect to Academia as an external agent using its own supported interface.

Start with `academia study capabilities --json`. Read [the study interface and examples](docs/study.md) for source retrieval, conversational practice, saved preferences, corrections, source-change detection and JSON/Markdown backup. Study data stays local under each course's `06_KNOWLEDGE/STUDY/`. Explicit generation sends selected excerpts to the chosen provider; it does not submit work or change real grades. Dashboard chat history is stored separately in local browser storage, not in the academic workspace.

## Install the core locally

Requirements: Python 3.11+ and Node.js/npm for the browser dashboard.

### Easiest macOS setup

After downloading or cloning the repository, run the included installer once:

```bash
cd academic-os-core
sh install-mac.sh
```

The installer creates a repository-local Python environment, installs Academia OS and its dependencies, installs the locked frontend dependencies, builds the dashboard, creates a per-user `academia` launcher in `~/.local/bin`, and adds that directory to zsh’s path when needed. It is safe to run again; it will not overwrite an unrelated existing `academia` command.

Open a new Terminal after installation, or reload the current shell:

```bash
source ~/.zshrc
academia
```

After the one-time setup, `academia` works from any folder and opens the local dashboard. This setup does not require Hermes, an Apple-signed application, or a cloud service. Dependency installation requires the normal Python package and npm registries; the dashboard and academic data remain local after installation.

### For AI agents

When a user authorizes Codex, Hermes, Claude, ChatGPT/Work, or another local agent to set up this repository, the agent should read `AGENTS.md` and this README before acting. On macOS, the supported setup command is:

```bash
sh install-mac.sh
```

The agent should explain that this creates the repository-local `.venv`, installs the package and locked frontend dependencies, builds `frontend/dist`, creates `~/.local/bin/academia`, and may update `~/.zshrc` to expose the launcher. The agent should ask for the user’s approval before executing those system and dependency changes, then verify with:

```bash
academia --help
```

After setup, `academia` opens the dashboard. Agents should use the stable JSON CLI for workspace operations, preserve the user’s academic files, and follow the approval and prohibited-action rules in `AGENTS.md`. The installer does not choose, create, attach, or migrate a personal academic workspace on the user’s behalf.

### Manual/development setup

For a development environment without the launcher setup:

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

`workspace inspect` is read-only. `workspace attach` is preview-only unless `--apply` is supplied; attachment writes only the local profile and does not migrate, rename, move, rewrite, or index academic files. Generated profiles use schema version 3, resolve a real semester label, keep browser access off by default, and do not require Hermes. Existing schema-version-1 and schema-version-2 profiles migrate non-destructively; pre-playbook integration/automation fields are retained only under explicit `legacy_compatibility` metadata.

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
academia task list --json
academia task create --title "Draft the essay outline" --course "POL 2103 - Politics" --due-date 2026-10-20 --json
academia task update TASK_ID --due-date 2026-10-22 --json
academia task complete TASK_ID --json
academia task reopen TASK_ID --json
academia history list --course "POL 2103 - Politics" --semester "Fall 2026" --json
academia history add --course "POL 2103 - Politics" --kind essay --title "Essay 1" --status submitted --submitted-on 2026-10-08 --json
academia history update --course "POL 2103 - Politics" --id RECORD_ID --status graded --grade A --json
academia review --json
academia review decide REVIEW_ID use_new --json
academia review execute REVIEW_ID --json
academia review amend REVIEW_ID --task-title "Read Week 6" --due-date 2026-10-08 --json
academia domain --json
academia library --json
academia library --category syllabi --json
academia library --course "POL 2103 - Politics" --json
academia file-preview /path/to/active-semester-file.pdf --json
academia extract syllabus /path/to/syllabus.pdf --course "POL 2103 - Politics" --json
academia extract syllabus /path/to/syllabus.md --course "POL 2103 - Politics" --verified-current --apply --json
academia settings show --json
academia settings update --set student.name="Student" --json
academia inbox --json
academia activity --json
academia agents --json
academia capabilities --json
academia agent capabilities --json
academia agent playbooks --json
academia agent playbook daily_academic_brief --json
academia agent playbook course_source_sync --json
# Compatibility aliases:
academia agent recommendations --json
academia agent recipe daily_academic_brief --json
academia workflow preferences --json
academia workflow show daily_academic_brief --json
academia workflow set daily_academic_brief --set time=08:30 --set cadence=weekdays --set include_calendar=true --updated-by user --json
academia agent context --scope today --detail compact --json
academia agent context --scope semester --detail standard --json
academia agent context --scope course --course "POL 2103 - Politics" --detail compact --json
academia agent attention --json
academia agent changes --since CURSOR --json
academia import /path/to/file.pdf --destination /path/to/workspace/Fall\ 2026/COURSE/00_INBOX --json
academia import /path/to/unknown-file.pdf --destination /path/to/workspace/Fall\ 2026/00_INBOX --uncertain --json
academia watch --json  # one-shot scan of configured folders
```

Use `--profile /path/to/profile.json` when the profile is not at `~/.academic-os/profile.json`.

### Agent Setup Playbooks

Academia OS keeps local capabilities separate from portable external-agent guidance. `academia agent capabilities --json` describes what Academia itself implements. `academia agent playbooks --json` lists read-only Agent Setup Playbooks, and `academia agent playbook PLAYBOOK_ID --json` returns one machine-readable playbook.

The shipped playbooks are:

- Daily Academic Brief
- Course Source Sync
- Academic Library / Scholarly Research
- Calendar Awareness
- Academic Email Awareness
- General Web Research
- Community Research
- Practice Material Discovery
- Visual / Media Learning Sources

These are not integrations, connection checks, deployment manifests, or running automations. They do not read Gmail, calendars, course portals, browsers, libraries, communities, or the web. An authorized external agent compares each playbook with its own tools, asks the student, adapts the implementation, and verifies what it actually configured. Academia OS owns the local academic state and safety contract; the external agent owns its scheduler, tools, credentials, and external automation.

The older `academia agent recommendations` and `academia agent recipe` commands remain compatibility aliases for existing agents.

### My playbook preferences

The student can save desired playbook configuration locally without configuring any external service. The dashboard Settings → Agent setup playbooks cards expose the human-readable playbook guide and an expandable My playbook preferences editor. The editor starts with playbook defaults and can save structured overrides, custom instructions, optional notes for the implementing agent, and audit attribution.

For example:

```bash
academia workflow set daily_academic_brief \
  --set time=08:30 \
  --set cadence=weekdays \
  --set detail=compact \
  --set include_calendar=true \
  --set include_academic_email=true \
  --set check_course_sources_first=true \
  --custom-instructions "Keep the briefing short unless something important changed. Prioritize anything due in the next 3 days." \
  --external-setup-notes "Managed by my external AI agent." \
  --updated-by user --json
```

Read the saved configuration together with its playbook:

```bash
academia workflow preferences --json
academia workflow show daily_academic_brief --json
```

The show response contains canonical `recommended_playbook`, compatibility `recommended_recipe`, `saved_preferences`, and `effective_preferences`. The saved file is `<academic_root>/.academia/workflow_preferences.json`. It is local preference data, not an account-connection record: it never proves that Gmail, Calendar, a course portal, a browser, a scheduler, or any other external service is available or running. A new connection or automation still requires the agent to explain and obtain the required student authorization. Credentials, MFA codes, tokens, cookies, passwords, and API keys are rejected from preference values and notes.

### Agent Context and safe secondary material

`academia agent context --json` is the primary machine-facing interface. It composes existing state without duplicating it and returns a bounded bundle containing:

- workspace and semester identity;
- scoped courses, open tasks, current assignments, user-confirmed coursework history, and confirmed upcoming deadlines;
- relevant Library references and evidence references without automatically loading file contents;
- unresolved Review decisions translated into `attention.items` with a question, why human input is needed, evidence, choices, and linked action proposal;
- failed or pending processing, important unverified facts, recent Activity, capability categories, and controlled write locations.

Scopes are `workspace`, `semester`, `course`, and `today`. Detail modes are `compact`, `standard`, and `deep`; compact is recommended for routine agent turns. The course-scoped `assignment_history` records are stored under `<semester>/<course>/03_ASSIGNMENTS/Assignment_History.json`. Agents should retrieve a bounded preview or authorized file only after context identifies it. Coursework status is recorded only from a user report or authorized source; it never means Academia submitted work to a school portal.

`academia agent changes --since CURSOR --json` returns append-only Activity events oldest-first and a `next_cursor`. Reusing the cursor is idempotent. Academia accepts an Activity event ID or ISO timestamp as a cursor and does not store chat-session state.

Study practice is created and saved through `academia study` and the Courses → Study workspace. Academia no longer exposes a separate generated-document Library category or an artifact-writing command. Agents can still explain material in chat or create cited, structured practice sets in Study when the student asks.

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

The processing lifecycle is explicit. `academia process forget RECORD_ID` removes only a failed record whose source is missing from a direct semester or course `00_INBOX` folder, and records that cleanup in Activity.

```text
DETECTED → PENDING → PROCESSING → VERIFIED → ACKNOWLEDGED
                                  └→ FAILED → retry → PENDING
```

Manual imports of PDF, DOCX, PPTX, plain text, Markdown, and common image files launch a detached local worker after the copy completes. The worker extracts text with local deterministic extractors, stores a rebuildable cache in `.academia/extracted_sources.json`, verifies the source signature, and acknowledges the processing record. PPTX extraction reads visible slide text locally; it does not OCR embedded images or include speaker notes. On macOS, scanned PDFs and images use Apple Vision OCR locally; OCR text is marked with a verification warning. On systems without macOS Vision and Swift, text PDFs continue to extract normally and image-only PDFs/images remain in the inbox with `unsupported_without_ocr`. Processing does not move or rewrite sources, infer course facts, or follow instructions found in documents.

### How dashboard data is calculated

- **Courses** are recognized folders in the configured active-semester directory that contain `01_COURSE/`. A course card also reports visible material counted from that course.
- **Library** lists visible files in the active semester while excluding `.academia/`, hidden files, and known workspace control files. Document types come from simple folder/name signals: syllabus/course-outline names are **Syllabi & guides**; `03_ASSIGNMENTS/`, `04_EXAMS/`, and assignment/exam/quiz/essay/project names are **Assignments & exams**; `02_LECTURES/` and lecture/slide/recording names are **Lectures**; `05_REFERENCE/` and chapter/reading/reference names are **Readings**; `02_WEEKS/`, `06_KNOWLEDGE/`, and note/review/study/summary names are **Notes & study aids**; anything without a matching signal is **Other**. The first matching rule wins. This is metadata-based navigation, not AI classification or an authority claim. Inbox/organized location and current processing status are independent filters, so one item can be a reading, still in intake, and failed processing at the same time.
- **Tasks** come from Markdown checkboxes in a course’s `01_COURSE/Course_Status.md` and from structured `assignment`/`deadline` entities in `.academia/domain.json`. Structured entities are created through syllabus extraction/reconciliation with evidence and confidence. DOCX assessment rows and PDF assessment lines retain source locations; yearless dates use only an explicitly named academic term year. Each assessment appears once, with its deadline time and grade weight. User-confirmed `Submitted`, `Graded`, or `Completed` records in the course’s `03_ASSIGNMENTS/Assignment_History.json` close a matching task while preserving the original deadline evidence. Home and Tasks show upcoming dates, and Tasks includes a next-seven-days filter. Unknown dates and unrecorded completion stay visible. Academia OS does not turn arbitrary filenames or prose into tasks.
- **Inbox / intake** contains files present in course or semester `00_INBOX/` folders. Running `academia inbox` detects pre-existing files into the retryable processing state machine. Detection alone does not classify, move, or delete a file.
- **Review** contains only explicit `.academia/review.json` items, such as uncertain imports, source conflicts, or approval-required actions. An unprocessed inbox file is shown as intake until a deliberate Review item is created.
- **Activity** is the append-only audit view of changes Academia OS actually completed. Reads, scans, and external agent conversations do not appear as changes unless the core performed a recorded action.
- **Coursework History** is a per-course record of assignments, essays, projects, exams, presentations, quizzes, and other academic work. The dashboard can add and update these records; status changes remain in the record’s status log and are reflected in matching tasks. This academic history is separate from dashboard chat history, which is retained in browser storage on the current device and can be deleted from Chat History.
- **File previews** are read-only and active-semester scoped. Markdown/text/CSV/JSON/YAML are shown as text; DOCX/PPTX text is extracted locally; PDFs open in an in-app browser frame with a text fallback in the desktop shell. Originals are never rewritten.

### Ownership of AI, browser, and automation

Academia OS has no built-in AI requirement. The user’s chosen agent owns its model, credentials, local operating-system permissions, browser session, and schedule. The core exposes the same local CLI/API to Codex, Hermes, Claude, ChatGPT/Work, or another authorized tool.

The core retains an off-by-default browser policy because it must be able to deny an adapter’s request even when an agent asks for it. This is a safety guard, not a browser connection. Browser authentication remains user-controlled, and the current browser capability is read-only visible Chromium handoff. Academia OS also does not run a background automation daemon; recurring work belongs to an explicitly configured external agent or scheduler.

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

The current capability report is honest: manual import with background extraction for supported text and image files is available; macOS adds local OCR for scanned PDFs and images. One-shot watched-folder scanning is also available; Chromium is limited to optional visible handoff with an explicit allow-list and target; Firefox and Safari are planned, not claimed as connected. The user may choose Chrome, Firefox, Safari, or another profile. A dedicated school/research profile is recommended for privacy but not required. Domain allow-lists narrow intended access but are not a security guarantee.

For readings, prefer legitimate library, Omni/OpenAthens, publisher, DOI/open-access, institutional, or author-released access. Discovery-only sources do not authorize downloading an unclear copy. Academia OS does not implement payments; agents must never infer payment authorization. Any future payment capability would require explicit student confirmation. Never silently substitute an edition.

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
academia review amend REVIEW_ID --task-title "Read Week 6" --due-date 2026-10-08 --json
```

Supported source formats are PDF, DOCX, PPTX, plain text, Markdown, and common image files. Text-based PDFs retain page references; text and Markdown retain line/segment references; presentations retain slide references. PDF text extraction uses the lightweight `pypdf` dependency. PPTX extraction reads visible slide text from the local Open XML package and warns that embedded images and speaker notes are not extracted. On macOS, scanned PDFs and images use local Apple Vision OCR, with page and text limits and an explicit warning that OCR may contain errors. No source is sent to a model or hosted service. On other platforms without a local OCR provider, scanned PDFs and images return `unsupported_without_ocr`; normal manual import still preserves them in `00_INBOX/`.

The first syllabus extractor only proposes course identity, assignments, explicit deadlines, assessment weights, required readings, and recurring course meetings. It does not interpret every date, policy, biography, URL, or arbitrary note. Missing dates, years, times, weights, pages, and course identity remain null or produce a warning. `current-confirmed` is used only when the user explicitly marks the supplied syllabus as current; otherwise directly stated facts are `likely` and ambiguous facts are `unverified`.

Preview mode does not write the domain projection, source file, workspace files, Review, Action, calendar, or school account. Apply mode adds safe derived entities and creates typed Review items for conflicts. A changed deadline never silently replaces an existing value: the proposal contains before/after values plus both evidence records. `use_new` approves the exact `DOMAIN_CHANGE`; execution rereads `.academia/domain.json`, verifies every requested field, resolves Review, and records Activity. A failed reread rolls back the derived update where possible, marks the proposal failed, reopens Review, and records the failure.

## Safety and privacy

- Originals are preserved; copies and collision-safe names are preferred.
- Destructive changes require an approved proposal.
- Calendar changes require approval and duplicate checking.
- No coursework, quiz, exam, form, discussion, or other academic work submission is implemented; no school-account messaging is implemented.
- Academia OS does not implement payments. Agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.
- Passwords, MFA codes, cookies, session tokens, and hidden secrets are not read or stored.
- School/browser access is optional and read-only in the current architecture.
- Local health verification is separate from safe-to-share auditing:

```bash
python -m installer.verify /path/to/profile.json
python -m installer.verify /path/to/profile.json --share-audit /path/to/export
```

An email address or local path can be normal in a private workspace; it should be reported by the share audit, not treated as a broken local installation.

## Review and activity

Uncertain source matches, deadline conflicts, and approval-required changes remain durable structured Review records under `.academia/review.json` for agent and CLI workflows. Action-linked records contain the exact `action_proposal_id`; approving one approves that proposal, and it resolves only after execution and verification. Activity events are append-only JSON lines under `.academia/activity.jsonl`. In the dashboard, unresolved activity remains in Recent; resolved items appear in Recent for 3 days and Archive for up to 90 days. Older items leave the UI, while the local audit log remains available for agent sync and audit history. The current dashboard does not yet present a built-in Review queue; that is part of the in-app assistant host work. Activity remains the user-facing audit trail of changes the core actually made.

## Desktop application

The modern frontend lives under `frontend/`:

```bash
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

It is a React + TypeScript application with a Tauri 2 shell and a typed bridge to the `academia` CLI. It includes profile-free first-run onboarding, existing-workspace inspection/attachment, fresh-workspace setup, Home, semester-scoped **Courses**, Tasks, Activity, and local Settings views. Courses is also the academic library: choose a semester, open a class, then browse Syllabi & guides, Readings & references, Lectures, Assignments & exams, Notes & study aids, and other files with bounded read-only previews for supported text, PDF, DOCX, and PPTX files. Folder location (intake or organized) and processing status are separate filters. The top-right profile badge opens a panel for Import material or **Migrate older material** instead of adding separate navigation sections. Settings edits local profile/workspace/import preferences, with playbook preferences sharing the CLI contract. Study chat invokes the installed Codex CLI; provider connection settings and external-service connectors are not yet implemented. The migration view scans an explicitly selected legacy folder, previews every destination, supports selected copy by default, and gates destructive Move behind an additional confirmation. Import uses the native Tauri file picker and drag/drop paths while delegating copying, processing, provenance, Activity, and uncertainty records to the existing CLI/core. The local stdio MCP supports bounded reads, host-gated file import, executable-choice-validated Review decisions, and separate execution for already-approved supported domain changes. It cannot verify that a host showed a confirmation, and has no browser/email/calendar connection. Study practice and saved sets are handled in the Study workspace; the app does not create separate AI-generated Library documents. The macOS distribution path bundles the local CLI and MCP server and supports signed in-app updates. Beta builds use an Academia-specific self-signed code identity and a separate Tauri updater key; they are not notarized, so first launch may require a Gatekeeper approval. The workflow creates draft Apple Silicon and Intel releases. See [the desktop release and MCP guide](docs/desktop-release-and-mcp.md). Windows and Linux packaging remain future work. The old Tkinter app remains as a compatibility fallback while the new shell matures.

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
