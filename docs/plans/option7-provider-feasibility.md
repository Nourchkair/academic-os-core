# Option 7 provider feasibility gate

**Status:** Pending live verification. No model inference has been requested.

## Installed client

- `codex` 0.139.0 at `/opt/homebrew/bin/codex`.
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

## Gate checklist

- [x] Local client detected and protocol schema inspected.
- [x] Candidate provider paths identified.
- [x] No unauthorized OAuth or API-billing path added.
- [ ] One live authenticated request with a verified provider.
- [ ] Structured tool call observed end to end.
- [ ] Streaming or progress events observed.
- [ ] Cancellation/interrupt observed.
- [ ] Auth failure, rate limit, timeout, and malformed tool call behavior recorded.
- [ ] Exact disclosure and plan-usage behavior documented.
- [ ] One disposable-workspace read-only workflow demonstrated.

## Decision rule

The Agent experience remains feature-flagged and is not described as functional
until this gate passes. Phase 2 runtime work uses `FakeProvider` for deterministic
tests and must not imply that a real provider is connected.
