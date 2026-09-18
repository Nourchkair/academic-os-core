# AGENTS.md — Academia OS agent guidance

## What this repository is

Academia OS is a local-first academic operating system. It is the product and owns the workspace model, provenance, source verification, review queue, activity history, migration, safe action proposals, and structured local interface. Hermes is only an optional adapter.

Compatible agents may include Hermes, Codex, ChatGPT/Work, Claude, or future tools. An agent must use the documented Academia OS interface instead of reverse-engineering the workspace Markdown tree.

## Installation and launch

For a fresh macOS checkout, the supported one-time setup is:

```bash
sh install-mac.sh
```

The installer creates the repository-local `.venv`, installs the Python package, installs locked frontend dependencies, builds `frontend/dist`, creates `~/.local/bin/academia`, and adds that directory to zsh’s `PATH` when needed. It may use the Python package and npm registries during installation, but the dashboard and academic workspace remain local afterward. It does not select, create, attach, migrate, or reorganize a personal academic workspace.

An agent must explain these effects and obtain user approval before running the installer. After setup, verify the launcher with `academia --help`; `academia` then starts the local server and opens the browser dashboard. Use `academia dashboard --no-open` when a browser should not be opened. If Python 3.11+ or Node.js/npm is unavailable, stop and report the prerequisite instead of installing system software without approval.

## Where state lives

- Human-readable academic material lives under the configured `academic.root_directory`.
- Rebuildable local indexes and workflow state live under `<academic.root_directory>/.academia/`.
- The canonical profile is the configured `runtime.install_directory/profile.json`.
- `profile.json` is local configuration. Never copy it to a public repository or share it without a safe-to-share audit.

The workspace must remain readable without Academia OS. Indexes and caches must be rebuildable from the underlying files whenever possible.

For each recognized semester, the reusable template includes a semester-level `00_INBOX/` for academic material whose course identity is not known yet. It is distinct from a course's direct `00_INBOX/`; imports must target exactly one of those two structures and may not use arbitrary dump folders or nested subfolders.

## Stable interface

Use the installed CLI or its equivalent local API:

```text
academia status --json
academia workspace --json
academia workspace discover --json
academia workspace inspect /path/to/workspace --json
academia semester --timezone America/Toronto --json
academia workspace attach /path/to/workspace --name "Student" --institution "University" --timezone America/Toronto --json
academia import /path/to/file.pdf --destination /path/to/workspace/SEMESTER/COURSE/00_INBOX --json
academia courses --semester "Fall 2026" --json
academia course "COURSE ID" --json
academia today --json
academia tasks --json
academia review --json
academia review decide REVIEW_ID use_new --json
academia review execute REVIEW_ID --json
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --json
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --verified-current --apply --json
academia domain --json
academia library --semester "Fall 2026" --json
academia library --semester "Fall 2026" --category imports --json
academia file-preview /path/to/semester-file.pdf --semester "Fall 2026" --json
academia settings show --json
academia inbox --json
academia activity --json
academia capabilities --json
academia verify-source --requested requested.json --retrieved retrieved.json --json
```

JSON output is the preferred agent context format. Human-readable output is for users.

## Allowed behavior

An agent may, when operating through the user-approved local interface:

- read structured workspace status, courses, tasks, library material, review items, activity, and source metadata;
- stage user-selected files through manual import or configured watched folders;
- create a plan or action proposal;
- create user-authored or AI-generated secondary material with explicit provenance;
- update rebuildable indexes and append activity records;
- perform non-destructive, verified file copies when the user has approved the proposal;
- prepare a settings diff for the user to review.

## Approval boundaries

- Calendar changes require an explicit approval proposal and duplicate check.
- Destructive changes, moves, renames, or structural workspace changes require explicit approval and a visible impact summary.
- A failed action remains failed/retryable; it is never acknowledged as successful.
- Review items remain open until a human decision is recorded.

## Prohibited behavior

Never:

- submit an assignment, quiz, exam, discussion, form, or other academic work;
- send messages through a university/school account or contact professors, students, TAs, or staff;
- make a payment;
- authenticate as the user or collect passwords, MFA codes, cookies, session tokens, or hidden API keys;
- casually overwrite or delete academic files;
- invent courses, deadlines, readings, editions, or institutional facts;
- silently substitute a source edition;
- treat an unverified fact as confirmed;
- claim an adapter is connected when it is only planned or detected.

School websites are read-only unless a future feature has an explicitly designed and approved safety boundary. Browser access is optional and defaults off.

## Provenance and confidence

Academic facts should carry confidence such as `current-confirmed`, `likely`, `unverified`, or `historical`. Material should carry provenance such as `ORIGINAL`, `USER-CREATED`, `AI-GENERATED`, or `EXTERNAL`. Preserve the source path, acquisition metadata, and verification result.

Source verification results include:

- `EXACT MATCH — HIGH CONFIDENCE`
- `PROBABLE MATCH — VERIFY MANUALLY`
- `MISMATCH`
- `NOT RETRIEVED`

## Acquisition

Manual import and watched folders are supported without browser access. Browser acquisition is adapter-based. The current Chromium capability is a visible, optional handoff only; Firefox and Safari adapters are planned and must not be represented as implemented. A future companion should use explicit actions such as “Send to Academia OS,” not broad background scraping.

Use a dedicated browser profile only as a recommendation. The user decides which browser/profile to use. Domain allow-lists reduce intended scope but do not guarantee isolation from every browser-level capability.

## Hermes adapter

Hermes-specific scheduling, skills, and detection live under `adapters/hermes/`. Do not add Hermes paths or commands to core modules. If Hermes is absent, Academia OS must still install, run, index, migrate, and serve the CLI/desktop interface.
