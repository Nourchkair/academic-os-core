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
- Student-owned workflow preferences live at `<academic.root_directory>/.academia/workflow_preferences.json`; they describe desired external workflow configuration, not connection or automation state.
- The canonical profile is the configured `runtime.install_directory/profile.json`.
- `profile.json` is local configuration. Never copy it to a public repository or share it without a safe-to-share audit.

The workspace must remain readable without Academia OS. Indexes and caches must be rebuildable from the underlying files whenever possible.

For each recognized semester, the reusable template includes a semester-level `00_INBOX/` for academic material whose course identity is not known yet. It is distinct from a course's direct `00_INBOX/`; imports must target exactly one of those two structures and may not use arbitrary dump folders or nested subfolders.

## Agent-first operating model

Academia OS is an AI-native academic operating layer. The student’s authorized AI agent owns conversation, reading, reasoning, teaching, synthesis, and repetitive maintenance; Academia OS owns academic state, evidence, provenance, permissions, safe actions, generated artifacts, and the audit trail. The dashboard is observational: it provides visibility, browsing, status, Activity, import/migration, local configuration, and Agent Setup Playbooks. It is not a chatbot or reasoning engine.

Keep these product layers separate:

- **Capabilities:** what Academia OS itself actually implements and can report through `academia agent capabilities --json`.
- **Agent Setup Playbooks:** portable, read-only guides describing a desired student workflow, required capabilities, safety boundaries, and verification contract.
- **External agent:** checks its own available tools, obtains any required authorization, and implements or adapts a selected playbook.
- **Student:** remains the final authority and chooses workflows and external access.

Academia OS owns local academic state, student preferences, provenance, Review, Activity, and safety boundaries. It does not own the external scheduler, browser session, account connection, credentials, or automation created by an external agent.

Academia must not claim Gmail, calendar, Brightspace, Canvas, Moodle, Blackboard, Omni, browser, scheduler, Reddit, web-search, or other external access merely because a playbook mentions it. It must not store external connection state or configure those systems itself.

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

## Agent Setup Playbooks

After Academia is installed and configured successfully, an authorized external agent should:

1. verify the local Academia interface;
2. inspect `academia agent playbooks --json`;
3. compare the playbooks with its actual capabilities;
4. tell the student which playbooks may improve the setup and which tools appear available in the agent environment;
5. offer guidance only for workflows the student wants;
6. obtain explicit authorization before external service access or automation is created;
7. retrieve the selected playbook with `academia agent playbook PLAYBOOK_ID --json`;
8. adapt the playbook to its own scheduler, browser, research, mail, calendar, or community tools while preserving the desired outcome and safety boundaries;
9. verify the setup through the playbook's verification steps;
10. report exactly what the external agent configured and what remains outside its capabilities.

The playbook commands are read-only. They do not create schedules, connect accounts, grant permissions, read external systems, or store integration status. A playbook is guidance and an implementation contract, not a deployment manifest. Existing `academia agent recommendations` and `academia agent recipe` commands remain compatibility aliases for older agents.

Saved workflow preferences are a separate, local student-owned layer. They are not external integration state and do not authorize a new external connection. The dashboard and an authorized agent read and write the same `<academic_root>/.academia/workflow_preferences.json` file through the workflow preference interface:

```bash
academia workflow preferences --json
academia workflow show daily_academic_brief --json
academia workflow set daily_academic_brief \
  --set time=08:30 \
  --set cadence=weekdays \
  --set include_calendar=true \
  --set include_academic_email=true \
  --set check_course_sources_first=true \
  --custom-instructions "Keep it short and prioritize the next three days." \
  --updated-by agent:codex --json
```

`workflow preferences` lists saved records without creating missing state. `workflow show` returns canonical `recommended_playbook`, a compatibility `recommended_recipe`, `saved_preferences`, and merged `effective_preferences`. `workflow set` validates overrides against the selected playbook, preserves unrelated existing overrides, writes atomically, and records `updated_at` plus an audit-only `updated_by` such as `user` or `agent:codex`. It never edits the static playbook. Agents must:

1. read the playbook;
2. read the saved workflow preferences;
3. treat them as the student's desired configuration;
4. explain any external authorization still required;
5. configure external tools only after the student's approval;
6. optionally update preference notes to describe maintenance choices; and
7. report what was actually configured, without claiming that saved preferences prove it is running.

Preference values and notes must not contain passwords, MFA codes, tokens, cookies, API keys, or other credentials. The workflow preference file is not an authentication mechanism.
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
academia agent playbooks --json
academia agent playbook daily_academic_brief --json
academia agent playbook course_source_sync --json
# Compatibility aliases for older agents:
academia agent recommendations --json
academia agent recipe daily_academic_brief --json
academia workflow preferences --json
academia workflow show daily_academic_brief --json
academia workflow set daily_academic_brief --set time=08:30 --set cadence=weekdays --updated-by user --json
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
- Academia OS does not implement payments. Agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.
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
