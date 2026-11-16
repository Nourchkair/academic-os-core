# 04 — Permissions and safety

Status: **frozen for Phase 1**

## Principle

The agent may reason, read, and propose. The student authorizes consequential
changes. The engine verifies what actually happened.

Approval is not verification. Execution is not approval.

## Actors and channels

An action records both the actor and the channel that invoked it.

```text
actor: user | student | agent:codex | agent:mcp | agent:assistant | system
channel: dashboard | cli_user | mcp | assistant | internal
```

- `user`/`student` on `dashboard` or `cli_user` is a user-authorized path.
- `agent:*` on `mcp` or `assistant` is an agent path.
- `system` is used only for migration, recovery, and automatic audit events.

The core cannot cryptographically prove that a human clicked a dashboard button.
It can enforce that agent channels never approve, and that every approval,
execution, and reversal records its actor and channel. Hosts must not expose an
approval tool to an agent.

## Permission matrix

| Capability | Agent | Student | Notes |
| --- | --- | --- | --- |
| Read knowledge/read model | Yes | Yes | Bounded, course-scoped |
| Read evidence references | Yes | Yes | Source bodies remain separately bounded |
| Propose ChangeSet | Yes | Yes | Proposal records evidence |
| Approve ChangeSet | **No** | Yes | Agent self-approval is prohibited |
| Execute an approved ChangeSet | Yes, after approval | Yes | Must pass approval hash and revision checks |
| Retry failed operations | Yes, after approval | Yes | Only failed/blocked operations |
| Reverse a ChangeSet | **No** in Phase 1 | Yes | Agent may propose a reversal separately |
| Approve a reversal | **No** | Yes | Reversal is consequential |
| Create/pause a task link | **No** without explicit student confirmation | Yes | Link creation is a relationship decision |
| Edit canonical academic files directly | **No** | Through existing UI/CLI | Must use the ChangeSet path for consequential changes |
| Trusted auto-apply | **Deferred** | — | No category grants in Phase 1 |

## Consequential changes

Phase 1 treats these as consequential and requiring explicit student approval:

- assessment deadline;
- due date of a task explicitly linked to an assessment;
- pausing or creating a mirror link;
- reversal of any executed ChangeSet.

These are non-consequential and may be agent-created without approval:

- assertions marked `active` but not applied;
- ChangeSet drafts/proposals;
- read-only explanations and impact previews;
- Activity entries.

Creating a proposal does not change an academic value.

## Agent self-approval prohibition

The following are rejected with `PermissionError`:

- `approve_changeset(actor="agent:*")`;
- `approve_changeset(channel="mcp" | "assistant")`;
- `reverse_changeset(actor="agent:*")`;
- an MCP/assistant tool named approve/execute/reverse for a ChangeSet.

The CLI exposes approval for the local user. An agent that invokes the CLI must
use `--actor agent:*`; a host that lies about its actor is outside the threat
model of a local-first application. The documented contract and the MCP surface
still prohibit it.

## Execution authorization

Execution requires:

1. ChangeSet status `approved`;
2. an approval record for the current `version`;
3. `approval_hash` matching the current payload;
4. every executed operation in `approved_operation_ids`;
5. dependencies satisfied;
6. target revision matching or idempotent after-state.

An execution request for an unapproved operation is rejected. It is not silently
dropped.

## Trusted actions

Existing action tiers and trusted MCP categories remain in place for their
current domains. They do not automatically authorize the new academic knowledge
operations.

Phase 1 adds **no** trusted auto-apply for:

- assessment deadlines;
- assessment weights;
- linked task due dates;
- mirror links;
- reversal.

A future trusted policy must be category-specific, explicit, auditable, and
revocable. It must never allow an agent to approve its own consequential
proposal.

## Prohibited behavior

The engine must never:

- submit academic work;
- contact instructors or students;
- authenticate as the student;
- collect passwords, MFA codes, cookies, or tokens;
- rewrite an original source document;
- delete an assertion, journal event, or approval record;
- mark a legacy record as verified or user-confirmed during migration;
- infer a task link from matching dates or titles;
- overwrite a later student change during reversal;
- claim a failed or partial operation succeeded;
- silently choose between conflicting sources;
- claim external calendar or school-portal access in Phase 1.

## Audit requirements

Every consequential action records:

- ChangeSet ID and version;
- actor and channel;
- approval hash;
- operation ID, target, before, after;
- evidence IDs;
- execution attempt and result;
- verification read-back;
- reversal outcome.

Activity records the summary. The ChangeSet journal records the detail. Neither
is a chat transcript.

## Failure disclosure

The UI and agent must disclose:

- which operations verified;
- which failed or were blocked;
- which were skipped by the student;
- which are irreversible;
- what remains inconsistent;
- whether a source is stale or unverified.

A failed action remains failed/retryable. It is never acknowledged as successful.

## Related contracts

- [03-change-coordination.md](03-change-coordination.md)
- [05-migration-and-compatibility.md](05-migration-and-compatibility.md)
- [06-ux-contract.md](06-ux-contract.md)
