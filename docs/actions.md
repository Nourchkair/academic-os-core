# Workspace actions

Every change the in-app agent can make goes through one catalog. An action is
validated, previewed, stored as an `ActionProposal`, then executed by an
executor that verifies its own result.

## Tiers

| Tier | Meaning | Actions |
| --- | --- | --- |
| `inline` | One explicit student confirmation in the conversation, then execute. | `task_change`, `file_copy`, `grade_record`, `file_restore`, `course_create`, `semester_create` |
| `review` | A Review decision, then a separate execute. | `file_move`, `file_trash`, `calendar_change`, `configuration_change`, `domain_change` |

An unknown action type defaults to `review`. `review` actions can never run
through the inline shortcut: the API returns `403 ReviewRequired`.

## Local API

```text
GET  /api/v1/actions/pending
POST /api/v1/actions/propose   {"action_type","details","title"?}
POST /api/v1/actions/execute   {"proposal_id"}
POST /api/v1/actions/discard   {"proposal_id"}
```

`propose` returns the proposal id, its tier, `requires_review`, and a preview:

```json
{
  "proposal_id": "…",
  "action_type": "file_trash",
  "tier": "review",
  "requires_review": true,
  "preview": {
    "title": "Move a file to trash",
    "summary": "Remove … from the workspace. It stays recoverable in .academia/trash.",
    "changes": [{"label": "File", "from": "Fall 2026/…/week1.md", "to": ".academia/trash"}],
    "targets": ["Fall 2026/…/week1.md"]
  }
}
```

The loopback dashboard is the only client. There is no remote endpoint and no
credential in any request.

## Guarantees

- **Nothing is deleted.** Trashing moves the file to
  `.academia/trash/<id>/` and records the original path, sha256, timestamp,
  proposal id, and actor in `.academia/trash/index.json`. Restore refuses if
  something already occupies the original path.
- **Every executor verifies.** Moves compare hashes before and after, grade
  records are read back from `Assignment_History.json`, and settings are
  re-read from `profile.json`.
- **Paths stay inside the workspace.** Actions reject parent segments, hidden
  segments, and anything that resolves outside the academic root.
- **Activity is appended** for `action.proposed`, `action.approved`,
  `action.executed`, `action.verified`, `action.failed`, and `action.discarded`.
- **Verification is stored** on the Review item and in Activity, including the
  trash id for restorable files.

## How the agent proposes

Two tools reach the same service:

- `academia_propose_action` over MCP, used by Codex proposal mode.
- `action.propose` in the assistant runtime registry, granted through
  `ToolGrant` for API model providers.

API providers may enable Proposal mode with the `Actions` grant only. Task,
import, and calendar proposals remain Codex-only. Runs are capped at
`max_iterations` (default 8, hard maximum 32) so a model cannot loop.

## Where the student approves

Proposals appear twice, from the same record:

- **In the conversation** as a card on the assistant message. Inline actions
  show **Allow**, **Allow for this chat**, and **Refuse**; review actions show
  **Review this action** and **Refuse**. When several inline changes arrive
  together, one bar offers **Allow all**.

"Allow for this chat" remembers that action type for the current conversation
only. It resets when a new chat starts or another conversation is opened, and
later proposals of that type in the same chat apply without another prompt.
- **In the agent panel's Actions tab**, which lists every pending proposal with
  its tier, exact changes, and the same buttons.

Allowing an inline action runs it immediately and reports the verification
result on the card. Review actions open the linked Review item.

## Not implemented yet

- `file_move` only moves files, not folders; structural folder changes remain
  out of scope until there is a restore story for them.

## Decision help in Review

Review items that need judgment (import classification, course identity,
deadline or domain conflicts, source verification) expose a **Help me decide**
button. It sends the item, the real course list, and the exact decision ids
Review accepts to the configured API model, and returns two or three options.

The model never decides:

- Options whose decision id is not in `review_decision_ids()` are dropped.
- The recommended option is a badge, not a default.
- "Nothing fits, keep it unchanged" is a valid answer.
- Applying an option goes through the normal `review decide` path.

Action approvals do not show the button; they are approve or reject.
