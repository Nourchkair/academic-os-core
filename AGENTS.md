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

## Shared assistant and external-agent operating model

Academia OS is a local-first academic operating layer with two host paths: dashboard Study chat and compatible external agents such as Codex or Claude. Both must use the same Academia interfaces for academic context, evidence, provenance, permissions, safe actions, structured Study records, and audit history. Dashboard Study chat uses the user's installed Codex CLI signed in with ChatGPT for ordinary study chat. When the student enables Proposal mode, it uses the Codex app-server with the local Academia MCP in proposal-only mode, so it may create exact Review/Action proposals for a local import or personal-task create/update. Calendar create/edit proposals require a separate explicit Calendar proposal grant; the assistant cannot approve or execute any proposal, send mail, or write directly. Calendar changes are separately executed only after Review approval, duplicate checks, and post-write verification. Study chat may use Codex's built-in live web search only when the student explicitly enables it for the conversation; that is a Codex host capability, not an Academia search connector. Do not route Claude subscription OAuth through Academia: Anthropic reserves that sign-in for Claude Code and native Anthropic apps. Claude Code may still connect as a separate external agent. Settings can connect one Google account with read-only Gmail and Calendar scopes. Study chat can include bounded read-only Gmail and Calendar context only when the student enables the corresponding per-message grant. External browser, portal, and Academia-owned search connectors remain unimplemented; never claim that Study chat has those tools.

Keep these product layers separate:

- **Capabilities:** what Academia OS itself actually implements and can report through `academia agent capabilities --json`.
- **Agent Setup Playbooks:** portable, read-only guides describing a desired student workflow, required capabilities, safety boundaries, and verification contract.
- **Assistant host:** the in-app assistant or an external agent that reasons and coordinates tools. It may use only capabilities actually exposed and authorized in that host.
- **External agent:** checks its own available tools, obtains any required authorization, and implements or adapts a selected playbook.
- **Student:** remains the final authority and chooses workflows and external access.

Academia OS owns local academic state, student preferences, provenance, Review, Activity, and safety boundaries. The future in-app assistant may coordinate explicitly enabled local or remote MCP services. Connection metadata must remain local; secrets belong in the operating system's secure credential store, never in the academic workspace, profile.json, workflow preferences, or repository. External agents may continue using their separately configured services.

Academia must not claim Gmail, calendar, Brightspace, Canvas, Moodle, Blackboard, Omni, browser, scheduler, Reddit, web-search, or other external access merely because a playbook mentions it. The current app has a local Google connector for one account with Gmail read-only and Calendar read-only scopes; it is shown in Settings and stores OAuth client credentials and tokens in the macOS Keychain. Study chat can include bounded Gmail/Calendar context only after the per-message grant, and can create Calendar Review proposals only with its separate proposal grant. Calendar creation/editing requires duplicate checks, fresh Review approval, and read-back verification; no change occurs before the separate execute step. There is no portal connector or Academia-owned search connector. Codex's built-in live web search is available only when the student explicitly enables it in Study chat, and it must be described as a Codex capability rather than an Academia connector. A future connector must be explicitly configured and authorized, report its actual status, use least-privilege scopes, and preserve service-specific safety rules.

Agents must use the structured interface first and retrieve source content only when the context bundle identifies a relevant source. The bounded `sources.library_items` catalog includes metadata for syllabi, readings, lectures, assessments, notes, and other material; it includes `id`, name, workspace-relative path, course ownership, document category, inbox/organized location, current processing status when available, provenance, and source type, never file bodies by default. The Library omits the retired `AI_GENERATED` document folders. Do not recursively inspect the Markdown tree or read `.academia` files directly to reconstruct state.

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

Academia's core interface does not store external agent chat transcripts, prompts, model messages, credentials, or conversation history. The dashboard Study chat is a separate client-side feature: it saves conversation text, selected class/source references, and lightweight action-proposal summaries and Review ids in browser IndexedDB on the device. It does not save attachments or write chat transcripts into the academic workspace. Browser data can be cleared by the student; saved conversations can also be deleted from Chat History.

The dashboard Study chat currently uses Codex CLI signed in with ChatGPT. Claude subscription sign-in is not offered inside Academia because Anthropic restricts subscription OAuth to its own Claude Code and native apps; use Claude Code as an external agent through Academia's documented interface. Academia does not read or copy either provider's credentials and does not fall back to API billing. Codex chat offers model, reasoning, Fast mode, and image attachments. It accepts PDF, DOCX, PPTX, plain-text, Markdown, CSV, JSON, and YAML files. Chat messages and selected class/source references persist in browser IndexedDB on the current device and browser profile; they are not stored by the Academia API or in `.academia/`. Attachments and extracted text are sent to Codex only when the student submits a message, and attachment files, extracted text, and image previews are not retained in chat history. Saved conversations retain attachment names and types only; reopening a chat requires reattaching files. Study chat locally OCRs scanned PDF pages when Poppler `pdftoppm` and Tesseract are available; otherwise it reports omitted pages and incomplete coverage. OCR text is marked so the assistant can qualify uncertain wording. For each submitted message, the shared `study context --deep` interface searches the full extractable text of every selected source, including PDF pages beyond page 100. The dashboard batches large selections; each source is limited to 64 million extracted characters, and DOCX/PPTX extraction honors the archive's XML safety limits. Academia sends up to 128 relevance-ranked, page-addressed passages rather than every source body. The chat includes scanned-source counts and reports extraction/size limits so the assistant can disclose incomplete coverage. The ordinary Codex CLI invocation runs with tools, MCP, browser, shell, and session persistence disabled; source access stays within selected Academia Library IDs and attached files. When the student enables Proposal mode, the request uses the Codex app-server with an isolated `CODEX_HOME` and `academia mcp serve --proposal-only`. In that mode the assistant may use Academia read tools plus explicitly granted proposal tools: personal-task proposals and file-import proposals can be enabled independently. It cannot approve, execute, copy, or write. Browser dashboard proposal runs stream tool/proposal progress, show a Stop control that interrupts the model run, and refresh proposal status from Review. A proposed personal task can be edited in Review before approval. Proposal summaries, live statuses, and Review ids are saved in browser chat history, but approval and execution remain in Review. Settings includes an app-level ChatGPT device-code sign-in that uses Codex's official login flow; Academia never reads or stores Codex credentials. The packaged Tauri shell currently uses the non-streaming chat transport; streaming and Stop are browser-dashboard features until the native transport is updated.

The per-course `03_ASSIGNMENTS/Assignment_History.json` stores academic coursework records, not chat history. Read it through `academia history list --course COURSE --semester TERM --json` or the course-scoped `assignment_history` field in `academia agent context`. Add or update a status only when the student explicitly reports it or an authorized source confirms it. A `Submitted` record means the workspace records that report; Academia never submits work to a school portal. The dashboard offers History within each class, with create/update controls for assignment, essay, project, exam, presentation, quiz, or other records. Files are references inside the course folder; submitted files remain preserved.

## Studying through any authorized agent

Use the shared `academia study` interface for structured studying. The dashboard is one client, never a required step. Read [the study contract](docs/study.md) before adding study behavior. Start with `academia study capabilities --json` and `academia study preferences --course COURSE --json`. Retrieve selected course excerpts through `study context`; an agent can generate a cited payload itself and submit through `study create --input -`, with no second model call. Use `study start/session/reveal/answer` to teach in conversation, record only the student's actual answers/ratings, and resume the same session in either interface. Never invent an attempt, self-rating, reading completion or reported instructor feedback.

Study owns durable per-course `06_KNOWLEDGE/STUDY/study.json`: sets, citations, attempts, review schedules, annotations, exam scope and desired study preferences. This is student academic data, not a rebuildable cache or agent transcript. Use `study export/restore` for explicit backups; preserve originals and old attempts. `study revise` or `create/generate --supersedes` creates a new set version. Flag ambiguous questions instead of counting them against progress. Source-linked material remains AI-generated and non-authoritative. Written responses/flashcards require student self-assessment; keep these separate from objective multiple-choice results and real course grades.

Optional explicitly invoked study generation may use the student's Codex ChatGPT sign-in or a loopback local model server. Credentials remain with those providers. Academia stores desired study preferences but never provider credentials. Source metadata is returned first; bodies are retrieved only by a selected-source or topic request. Generation does not authorize school actions, external account access, calendar writes or automatic background model calls. An external Claude Code agent can generate a payload itself and submit it through `academia study create`.

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
academia process start PROCESSING_RECORD_ID --json
academia process forget PROCESSING_RECORD_ID --json
academia courses --semester "Fall 2026" --json
academia course "COURSE ID" --json
academia today --json
academia tasks --json
academia task list --json
academia task create --title "Draft the essay outline" --course "COURSE ID" --due-date 2026-10-20 --json
academia task update TASK_ID --due-date 2026-10-22 --json
academia task complete TASK_ID --json
academia task reopen TASK_ID --json
academia assistant propose-task --action create --title "Read Week 5" --course "COURSE ID" --evidence-source "Course reading list" --evidence-path "SEMESTER/COURSE/05_REFERENCE/reading.md" --json
academia history list --course "COURSE ID" --semester "Fall 2026" --json
academia history add --course "COURSE ID" --kind essay --title "Essay 1" --status submitted --submitted-on 2026-10-08 --artifact "03_ASSIGNMENTS/A01/Submission/final.docx" --json
academia history update --course "COURSE ID" --id RECORD_ID --status graded --grade A --json
academia review --json
academia review decide REVIEW_ID use_new --json
academia review execute REVIEW_ID --json
academia review amend REVIEW_ID --task-title "Read Week 6" --due-date 2026-10-08 --json
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --json
academia extract syllabus /path/to/syllabus.pdf --course "COURSE ID" --verified-current --apply --json
academia domain --json
academia library --semester "Fall 2026" --json
academia library --semester "Fall 2026" --location inbox --json
academia library --semester "Fall 2026" --category lectures --processing-status processed --json
academia file-preview /path/to/semester-file.pdf --semester "Fall 2026" --json
academia settings show --json
academia inbox --json
academia activity --json
academia review show REVIEW_ID --json
academia review decide REVIEW_ID DECISION --actor agent:mcp --json
academia review execute REVIEW_ID --actor agent:mcp --json
academia capabilities --json
academia mcp serve
academia mcp-connections list --json
academia mcp-connections add --name "Local research" --command /path/to/mcp-server --arg --stdio --json
academia mcp-connections inspect CONNECTION_ID --json
academia mcp-connections grant CONNECTION_ID --tool search_notes --json
academia mcp-connections call CONNECTION_ID --tool search_notes --arguments '{"query":"research"}' --json
academia mcp-connections disable CONNECTION_ID --json
academia mcp-connections disconnect CONNECTION_ID --json
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
academia verify-source --requested requested.json --retrieved retrieved.json --json
```

JSON output is the preferred agent context format. Human-readable output is for users. Any agent command that accepts `--course` resolves the exact canonical course ID, course code, or exact course name/display name to the same canonical course object. Unknown and ambiguous identifiers fail with a structured error; they never fall back to workspace-wide results.

`academia mcp serve` exposes a local MCP interface over stdio for compatible hosts. Read tools use bounded structured interfaces; Library previews require an exact workspace-relative Library ID and are revalidated by `academia file-preview`. Narrow write tools support host-gated local-file import, an exact executable Review decision, and a separate supported execution for an already-approved Review item. `--proposal-only` additionally exposes exact `academia_propose_import` and `academia_propose_task` tools that create Review/Action proposals without writing. The server cannot verify that a human confirmation was displayed; compatible hosts must obtain confirmation for the exact decision or file and destination before calling write tools. The Review decision tool rejects choices that do not exactly match an executable choice from current `academia agent attention` output. Review execution is limited to an already-approved linked `domain_change`, `file_copy`, or `task_change` action. Activity records identify MCP-initiated decisions and execution as `agent:mcp`. Imports preserve the original and start supported local extraction. Study sets and practice are managed through the Study interface. The server opens no network listener and has no external-service connectors.

`academia mcp-connections` manages explicit local stdio MCP connections. Metadata is stored only in the runtime directory, never in the academic workspace, profile.json, workflow preferences, or repository. Adding a connection does not start it. `inspect` launches the server once, records its actual server identity and declared tools, and closes it. Only tools with `readOnlyHint: true` can be granted; non-read-only tools remain ungranted and are shown as not grantable. `enable` requires at least one read-only grant, `call` requires an enabled connection and a granted read-only tool, and `disable`/`disconnect` stop future use and remove the connection record respectively. Academia does not store credentials for these servers and does not claim an external integration works until inspection succeeds.

## Allowed behavior

An agent may, when operating through the user-approved local interface:

- read structured workspace status, courses, tasks, library material, review items, activity, and source metadata;
- stage user-selected files through manual import or configured watched folders; manual imports of locally supported formats launch deterministic background text extraction into rebuildable `.academia/extracted_sources.json`, including visible PPTX slide text (without embedded-image OCR or speaker notes), while preserving originals and never interpreting embedded instructions;
- import a specific local file through MCP only after the assistant host has asked the student to confirm the exact file and recognized inbox destination;
- create a plan or action proposal;
- run a provider-neutral assistant loop with only explicitly granted read and write tools; approval-gated tools route through Review, and create-only writes require host confirmation;
- create or update a user-owned personal task in `SEMESTER_TASKS.md` only through the direct user interface or an approved `task_change` Review action; only the student marks a task complete or reopens it;
- create structured source-linked study sets and record student practice through `academia study`;
- update rebuildable indexes and append activity records;
- perform non-destructive, verified file copies when the user has approved the proposal;
- prepare a settings diff for the user to review.

AI-created study aids belong in the structured Study workspace as source-linked sets and practice records. Academia does not expose a separate course-document generation or artifact-writing interface. Study data remains AI-generated and non-authoritative, with citations and student practice preserved in the course Study store.

`SEMESTER_TASKS.md` is the canonical user-task queue; there is no separate task database. One delimited structured block stores personal tasks, and unrelated Markdown is preserved byte-for-byte. Course-derived tasks and domain deadlines are separate read-only evidence. Agents may propose creating or updating a personal task only through `task.propose`, with an existing workspace file as evidence. They may never mark a task complete or reopen one on the student's behalf, and an approved task change never submits coursework, changes a grade, or alters a syllabus deadline. A malformed or duplicate task block fails closed.

## Approval boundaries

- Calendar changes require an explicit approval proposal and duplicate check.
- Destructive changes, moves, renames, or structural workspace changes require explicit approval and a visible impact summary.
- A failed action remains failed/retryable; it is never acknowledged as successful.
- Review items remain open until a human decision is recorded.

`academia agent attention --json` is the conversation-facing Review contract. Each unresolved item includes `id`, `kind`, `course`, `question`, `why_this_needs_human_input`, `current_value`, `proposed_value`, `evidence`, `choices`, `recommended_next_actions`, `action_proposal_id`, and `status`. `choices[]` means a stable decision that Academia can accept through the existing Review contract; each executable choice includes `id`, `label`, `effect`, `executable: true`, and a structured `action` descriptor. For a supported action, the descriptor identifies the Review decision and, when needed, the separate `review_execute` step. `recommended_next_actions[]` is different: every entry has `executable: false` and is guidance only. It may say `verify_source` or `retry_processing`, but those labels are not claims that a corresponding command exists. Today, linked domain-change, file-copy, and personal-task Reviews can expose an approve decision followed by `review execute`; processing retry and source verification remain advisory. The agent asks the student, submits only an executable Review choice, performs the separate execution step only when advertised, and verifies the result. Review remains a backend protocol; it is not a chat transcript or an instruction to guess.

`academia process forget RECORD_ID --json` removes a processing record only when it is `FAILED`, its source is missing, and its recorded path is a direct semester or course `00_INBOX` entry in the configured workspace. It preserves the source file (if present, the command refuses) and appends a `processing.forgotten` Activity event.

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
