# Option 7 Phase 3 write and approval slice

**Status:** Implemented in the `option7/foundation` branch. The Codex app-server
path remains read-only; write execution is available through the shared core,
CLI, and Review workspace.

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

## Boundaries

- The Codex app-server runtime remains read-only and exposes no write tools.
- Task writes remain deferred.
- Codex MCP write-tool execution still requires a host confirmation UI before it
  can be enabled.
- The Review UI displays exact local targets and effects; it does not treat a
  model recommendation as approval.
