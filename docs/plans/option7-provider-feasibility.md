# Option 7 provider feasibility gate

**Status:** Read-only tool-using workflow passed with Codex 0.167.1 and
`gpt-6-luna`. Write/approval provider integration remains Phase 3 work.

## Installed client

- `codex` 0.167.1 at `/opt/homebrew/bin/codex` (updated from 0.139.0 during the
  probe).
- `codex app-server` is marked experimental but exposes `stdio`, `unix`, and websocket transports.
- `codex app-server generate-json-schema` produced the local protocol schema bundle on 2026-11-11.

## Verified protocol surface (schema inspection only)

- `thread/start`, `thread/resume`, `thread/fork`, `thread/read`.
- `turn/start`, `turn/steer`, `turn/interrupt`.
- Streamed notifications including `item/agentMessage/delta`, `item/reasoning/*`, `turn/completed`, and `item/mcpToolCall/progress`.
- `item/tool/call` server request with `DynamicToolCallParams` / `DynamicToolCallResponse`.
- `mcpServer/tool/call` client request and MCP server status/tool metadata.
- Approval requests for command execution, file changes, permissions, and user input.

## Candidate paths

### A. Codex app-server with Academia MCP as a read-only tool server

Register the installed Academia stdio MCP server with Codex, start an ephemeral
read-only thread, and let Codex request Academia tools. The MCP server remains
the authority for read-only tool selection and result bounds.

**Advantages:** existing ChatGPT sign-in, existing Academia MCP, streamed events,
cancellation, and no new OAuth path.

**Risks:** Codex MCP tool calls bypass the in-process `RunController` registry;
we must observe `item/mcpToolCall` events and verify scope/argument safety from
events. The MCP server currently exposes some write tools, so the first probe
must use a filtered read-only server or a read-only profile.

### B. Codex app-server dynamic tools

Use `item/tool/call` to route model tool calls into the in-process registry.

**Advantages:** our `RunController` remains the executor and policy authority.

**Risks:** the schema includes the request/response types, but the exact way to
register dynamic tool specs is not documented in the generated bundle. This
needs a live protocol probe before it can be the primary path.

### C. Loopback OpenAI-compatible provider

Use native tool calling from a local model server.

**Advantages:** clean provider-neutral tool loop; no subscription ambiguity.

**Risks:** requires a model/server the student has installed; few students do.

## Probe results — 2026-11-11

The app-server path started successfully against a disposable workspace with an
isolated `CODEX_HOME` and a symlinked existing ChatGPT auth file:

- `initialize` and `thread/start` succeeded.
- The Academia MCP server launched with `mcp serve --read-only` and reported
  `mcpServer/startupStatus/updated` → `ready`.
- No academic file was modified.
- No MCP tool call was reached because the model turn failed.

The model gate failed with the installed CLI 0.139.0:

| Model | Result |
|---|---|
| `gpt-5.5` | `model_not_found` for this ChatGPT account |
| `gpt-5.4-mini` | `model_not_found` for this ChatGPT account |
| `gpt-5.2` | `model_not_found` for this ChatGPT account |
| `gpt-5.3-codex` | `model_not_found` via `codex exec`; app-server turn stalled/system-error |
| `gpt-6-luna` | app-server warned “Model metadata not found” and stalled; `codex exec` returned `model_not_found` |

`codex doctor` reported that Codex 0.167.1 was available while the installed
client was 0.139.0. The model names configured for the desktop app were newer
than that CLI’s supported ChatGPT model set.

## Success after updating to 0.167.1

After updating Codex, the same isolated probe passed:

- `gpt-6-luna` completed a live turn.
- The model requested `academia_library` through the `academia` MCP server.
- `item/mcpToolCall` started and completed with the Library result.
- The model streamed `item/agentMessage/delta` events and answered exactly
  `week-4-reading.md`.
- Academic files remained unchanged.
- Read tools carry `readOnlyHint: true`, so the read-only call did not require a
  write-style approval prompt under `approvalPolicy: never`.
- A second probe sent `turn/interrupt`; the turn completed with status
  `interrupted` in 19 ms and academic files remained unchanged.

The prior 0.139.0 `model_not_found` responses remain the recorded
authentication/entitlement failure evidence. Rate-limit and malformed-tool-call
behavior are still not exercised by this probe.

## Gate checklist

- [x] Local client detected and protocol schema inspected.
- [x] Candidate provider paths identified.
- [x] No unauthorized OAuth or API-billing path added.
- [x] App-server handshake and read-only Academia MCP startup verified.
- [x] One live authenticated request with a verified provider (`gpt-6-luna`).
- [x] Structured tool call observed end to end (`academia_library`).
- [x] Streaming or progress events observed (agent deltas and MCP call events).
- [x] Cancellation/interrupt observed (turn status `interrupted`).
- [x] Authentication/entitlement failure observed (older CLI model mismatch).
- [ ] Rate limit and malformed tool call behavior recorded.
- [ ] Exact disclosure and plan-usage behavior documented beyond plan limits.
- [x] One disposable-workspace read-only workflow demonstrated.

**Gate decision:** read-only provider path is viable. The first-party Agent UI
can proceed behind a feature flag, but must not be described as fully functional
until Phase 3 write approvals and the remaining failure cases are tested.

## Implemented backend

`academia_os/assistant/providers/codex_app_server.py` now implements
`CodexAppServerRuntime`:

- Creates a temporary, permission-restricted `CODEX_HOME`.
- Symlinks the existing Codex `auth.json`; it never copies or reads credentials.
- Writes a minimal config exposing only `academia mcp serve --read-only`.
- Disables shell, multi-agent, apps, plugins, and web search for the turn.
- Starts an ephemeral read-only thread and one turn.
- Maps MCP tool calls, message deltas, completion, interruption, timeout, and
  provider errors into `RunResult`/`RunEvent` objects.
- Supports `CancelToken` through `turn/interrupt`.

CLI:

```bash
academia assistant run --message "List one Library item" --json
```

Live verification on a disposable workspace returned
`week-4-reading.md`, with one `academia_library` tool result and no file changes.
A second live run used `--course "POL 2103"` against a workspace containing a
second course; the MCP server returned only the selected course's material.
The selected scope is now enforced by `academia mcp serve --semester ... --course ...`
and passed through by `CodexAppServerRuntime`.

## Decision rule

The Agent experience remains feature-flagged and is not described as functional
until this gate passes. Phase 2 runtime work uses `FakeProvider` for deterministic
tests and must not imply that a real provider is connected.
