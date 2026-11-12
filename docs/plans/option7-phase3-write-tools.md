# Option 7 Phase 3 write and approval slice

**Status:** Implemented in the `option7/foundation` branch. The Codex app-server
path remains read-only by default and proposal-only on request; write execution
is available through the shared core, CLI, and Review workspace.

## Import proposal and execution

```bash
academia assistant propose-import \
  --source ~/Downloads/lecture.pdf \
  --target "Fall 2026/POL 2103 - Politics/00_INBOX" \
  --json
academia review decide REVIEW_ID approve --json
academia review execute REVIEW_ID --json
```

- `import.propose` creates an Action and Review with exact source, destination,
  SHA-256, size, and effects. It copies nothing.
- `review decide` records approval or rejection.
- `review execute` revalidates the source hash, copies atomically, records
  acquisition provenance, starts supported local processing, and verifies the
  destination hash.
- A changed source invalidates the approval, fails safely, and reopens the
  Review.
- Replaying a verified action is rejected.

## Study creation

`study.create` creates one cited, non-authoritative Study set through the
canonical `StudyService`. It is create-only; existing sets and attempts are
preserved. The existing `academia study create` CLI remains the external-agent
interface.

## Domain changes

`domain.propose` creates an evidence-backed Review/Action proposal for a derived
academic fact. It does not change the projection. After approval, the existing
`review execute` path runs `execute_domain_change`, verifies the readback, and
records Activity. Stale values fail safely and remain retryable through a new
proposal.

## Personal tasks

`SEMESTER_TASKS.md` is the canonical user-task queue. Its single delimited JSON
block is written atomically; unrelated Markdown is preserved. Derived course
tasks from `Course_Status.md` and domain deadlines remain read-only evidence.

```bash
academia task list --json
academia task create --title "Draft the essay outline" --course "POL 2103" \
  --due-date 2026-10-20 --due-time 09:00 --json
academia task complete TASK_ID --json
academia task reopen TASK_ID --json
academia task update TASK_ID --due-date 2026-10-22 --json
```

- A malformed or duplicate task block fails closed; the file is never replaced.
- Completion changes only that personal task. It never submits coursework,
  changes a grade, or alters a syllabus deadline.
- Course history overlays never complete a user task.
- Every write is atomic and appends Activity.

Agent-proposed changes use `task.propose`:

```bash
academia assistant propose-task \
  --action create \
  --title "Read Week 5" \
  --course "POL 2103" \
  --due-date 2026-10-01 \
  --evidence-source "Course reading list" \
  --evidence-path "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md" \
  --json
academia review decide REVIEW_ID approve_action --json
academia review execute REVIEW_ID --json
```

- Proposals may create or update a personal task; they cannot mark work complete.
- Evidence must identify an existing workspace file.
- The proposition validates the exact future task before creating Review.
- Execution revalidates the task's `updated_at`; a student edit after approval
  fails safely instead of overwriting the edit.
- Created tasks carry `AI-GENERATED` provenance and remain non-authoritative.

## Review workspace

The dashboard now has a first-class **Review** page:

- Typed decision cards for conflicts, imports, course identity, and source
  verification.
- A separate **Execute approved action** step. Approval alone changes nothing.
- An approval timeline for proposals, decisions, execution, verification, and
  failure.
- Home’s open-decision count links directly to Review.

Approved action-linked items remain visible after restart through
`academia review list --pending-execution`.

## Codex proposal mode

A probe showed that Codex app-server can execute a non-read-only MCP tool without
sending an approval request to the host, even with `approvalPolicy: on-request`.
Direct write tools are therefore **not** exposed to Codex.

`academia assistant run --proposal-mode` starts the app-server with
`academia mcp serve --proposal-only`. In that mode Codex may create an exact
`academia_propose_import` or `academia_propose_task` proposal, but cannot copy
files, write tasks, approve, or execute. The proposal appears in Review; only a
human can approve and run it.

Dashboard Study chat uses the same proposal-only path when the student enables
**Proposal mode**. The chat can create task/import proposals, renders the exact
before/after, effects, and Review id, and links to the matching Review card.
Ordinary chat remains tool-disabled. The chat cannot approve or execute, and no
academic file is written until the student acts in Review.

## Boundaries

- Direct Codex write-tool execution remains disabled.
- Personal-task writes are available only through the user-facing CLI/dashboard
  or an approved Review action.
- The Review UI displays exact local targets and effects; it does not treat a
  model recommendation as approval.
