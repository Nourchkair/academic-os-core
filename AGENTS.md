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

## Agent-first operating model

Academia OS is an AI-native academic operating layer. The student’s authorized AI agent owns conversation, reading, reasoning, teaching, synthesis, and repetitive maintenance; Academia OS owns academic state, evidence, provenance, permissions, safe actions, generated artifacts, and the audit trail. The dashboard is observational: it provides visibility, browsing, status, Activity, import/migration, and local configuration. It is not a chatbot or reasoning engine.

Agents must use the structured interface first and retrieve source content only when the context bundle identifies a relevant source. The bounded `sources.library_items` catalog includes metadata for syllabi, readings, notes, generated artifacts, and relevant imports; it includes `id`, name, workspace-relative path, course ownership, category, provenance, source type, and artifact metadata, never file bodies by default. Do not recursively inspect the Markdown tree or read `.academia` files directly to reconstruct state.

Recommended request loop:

1. `academia agent capabilities --json`
2. `academia agent context --scope today --detail compact --json`
3. `academia agent attention --json`
4. Retrieve only the referenced course/source files through the bounded file interface.
5. Perform reasoning in the agent and ask the student when an attention item presents a meaningful decision.
6. If `choices` contains an entry with `executable: true`, present those choices exactly as returned. Submit the selected structured action with `academia review decide REVIEW_ID DECISION --json`.
7. If the selected action has `requires_execution: true`, call `academia review execute REVIEW_ID --json` as a separate step, then verify the result through `academia agent changes` or refreshed context.
8. Treat every entry in `recommended_next_actions` as advisory guidance. It is not an Academia command and must not be reported as performed.
9. Poll `academia agent changes --since CURSOR --json` on the next agent session instead of rereading everything.

Academia does not store agent chat transcripts, prompts, model messages, credentials, or conversation history.

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
academia agent capabilities --json
academia agent context --scope today --detail compact --json
academia agent context --scope course --course "COURSE ID" --detail standard --json
academia agent attention --json
academia agent changes --since CURSOR --json
academia artifact create --course "COURSE ID" --kind study_guide --title "Week 5 Study Guide" --content-file /tmp/guide.md --source "Fall 2026/COURSE ID/05_REFERENCE/week-5.md" --created-by codex --json
academia verify-source --requested requested.json --retrieved retrieved.json --json
```

JSON output is the preferred agent context format. Human-readable output is for users. Any agent command that accepts `--course` resolves the exact canonical course ID, course code, or exact course name/display name to the same canonical course object. Unknown and ambiguous identifiers fail with a structured error; they never fall back to workspace-wide results.

## Allowed behavior

An agent may, when operating through the user-approved local interface:

- read structured workspace status, courses, tasks, library material, review items, activity, and source metadata;
- stage user-selected files through manual import or configured watched folders;
- create a plan or action proposal;
- create AI-generated secondary material only through `academia artifact create`; the destination is always a recognized course’s `06_KNOWLEDGE/AI_GENERATED/` directory;
- attach workspace source references or evidence-backed domain references to generated material;
- update rebuildable indexes and append activity records;
- perform non-destructive, verified file copies when the user has approved the proposal;
- prepare a settings diff for the user to review.

Generated artifacts are Markdown/text secondary material. They are recorded with `provenance: AI-GENERATED`, `authoritative: false`, an optional `created_by` audit label, and source/domain references. Artifact creation is create-only in this pass: it cannot update, rename, delete, or overwrite an existing artifact or any ORIGINAL, USER-CREATED, or EXTERNAL material. Use a new artifact when a guide needs a revised version.

## Approval boundaries

- Calendar changes require an explicit approval proposal and duplicate check.
- Destructive changes, moves, renames, or structural workspace changes require explicit approval and a visible impact summary.
- A failed action remains failed/retryable; it is never acknowledged as successful.
- Review items remain open until a human decision is recorded.

`academia agent attention --json` is the conversation-facing Review contract. Each unresolved item includes `id`, `kind`, `course`, `question`, `why_this_needs_human_input`, `current_value`, `proposed_value`, `evidence`, `choices`, `recommended_next_actions`, `action_proposal_id`, and `status`. `choices[]` means a stable decision that Academia can accept through the existing Review contract; each executable choice includes `id`, `label`, `effect`, `executable: true`, and a structured `action` descriptor. For a supported action, the descriptor identifies the Review decision and, when needed, the separate `review_execute` step. `recommended_next_actions[]` is different: every entry has `executable: false` and is guidance only. It may say `verify_source` or `retry_processing`, but those labels are not claims that a corresponding command exists. Today, linked domain-change Reviews can expose an approve/use-new decision followed by `review execute`; processing retry and source verification remain advisory. The agent asks the student, submits only an executable Review choice, performs the separate execution step only when advertised, and verifies the result. Review remains a backend protocol; it is not a chat transcript or an instruction to guess.

`academia agent changes --since CURSOR --json` reads the append-only Activity feed oldest-first and returns `next_cursor`. Reusing that cursor is idempotent. The cursor is an Activity event id; an ISO timestamp is also accepted for integrations that persist time checkpoints.

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
