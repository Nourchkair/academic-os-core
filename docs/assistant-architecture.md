# Academia OS assistant architecture

## Product direction

Academia OS remains a local-first academic system. It supports two ways to use an assistant:

1. **In-app Study chat:** The dashboard invokes the user's installed Codex CLI session for ordinary study chat. When the student enables Proposal mode, it uses the Codex app-server with Academia's MCP server in proposal-only mode, so it can create exact Review/Action proposals for a local import or personal-task create/update but cannot approve, execute, or write. The student selects a model and only explicitly submitted context is sent to that provider. Claude subscription OAuth is not offered in Academia because Anthropic reserves it for Claude Code and other native Anthropic apps; Claude Code can connect as a separate external agent. External MCP connections are not wired into Study chat yet.
2. **External agent:** Codex, Claude, or another compatible host connects to Academia OS through its local CLI/MCP interface and uses its own provider and tools.

Both paths must use the same academic context, import, Study, Review, provenance, and Activity contracts. There must not be separate academic logic or a second academic database for the assistant.

## Components

```text
Dashboard assistant UI
  ├─ Study chat → Codex CLI ordinary / app-server proposal-only
  ├─ bounded context retrieval and Study generation
  └─ future MCP client/connection manager (user-enabled services only)
          │
          ▼
Shared Academia CLI/API/services  ◀── Codex / Claude / other external hosts
  ├─ bounded academic context and Library access
  ├─ import and processing lifecycle
  ├─ Study domain and saved practice
  ├─ Review / approval / verification
  └─ Activity and provenance
          │
          ▼
Local workspace files + local `.academia/` state
```

The assistant host chooses when to call tools. MCP servers expose tools and data; they do not supply a model. A single host can coordinate Academia and other user-enabled MCP servers. Academia's own MCP server does not automatically acquire browser, Gmail, calendar, or portal access.

## Local-first and provider boundaries

- Academic files and structured state stay on the student's computer. Study chat history stays in browser IndexedDB on that device/profile.
- Codex subscription-backed CLI requests receive only the current conversation, selected context/excerpts, and attached files submitted for that turn. The UI identifies the provider and describes the submitted context.
- Local-model requests use explicitly configured loopback endpoints. Academia does not silently download a model or start a model server.
- Codex credentials remain in the official CLI's local credential store. Academia does not read, copy, or store them. Do not put secrets in `profile.json`, workflow preferences, workspace files, app logs, the repository, or MCP tool output. Claude subscription credentials are not routed through Academia; use Claude Code directly as an external agent.
- Disable integrations by default. Show the service, granted scopes, local connection status, and a disconnect/revoke control. Report `unavailable` or `not configured` accurately.
- External agents continue using their own credentials and tools. Academia's app connections are not implicitly shared with Codex or another host.

## Tool permission classes

| Class | Examples | Policy |
|---|---|---|
| Read local context | Courses, tasks, source metadata, selected Library excerpts | Bounded by selected workspace/course/source; reads do not imply permission to send contents to a hosted provider. |
| Read external context | Calendar, email, portal pages, web results | Per-service user authorization and scoped read access. External sources carry provenance and confidence. |
| Create local secondary material | Study set, notes, outline, draft | Create-only in an allowed course location, source-linked where relevant, marked `AI-GENERATED` and non-authoritative. Never overwrite originals. |
| Import external/local files | Portal downloads into a course or semester inbox | Ask for confirmation of the exact file and target. Copy the file, preserve the original, process locally, and verify status. School website access remains read-only. |
| Consequential external/local actions | Calendar edits, file moves, settings changes | Prepare an impact summary and use the existing Review/approval/execution/verification flow. |
| Prohibited actions | Coursework submission, school-account messages, payments, credential/MFA/cookie access | Do not implement or expose these as tools. |

Attachments and source documents are untrusted data. Their embedded instructions never override assistant, tool, or safety policy.

## Portal-to-Academia workflow

The intended workflow is:

1. The student asks the assistant to find and import a course source.
2. An enabled browser tool performs visible, read-only portal navigation using the student's existing browser authorization. It downloads only the selected academic files.
3. The assistant presents the file name, source URL, course, and destination inbox.
4. After the student confirms, the Academia import action copies the file into the exact returned semester/course `00_INBOX`, preserves the original, records acquisition provenance, starts supported local extraction, and returns the processing record.
5. The assistant checks processing status and reports success or a retryable failure. It does not mark a source verified or authoritative solely because it downloaded or extracted successfully.

The portal browser connector and in-app tool orchestration are future work. The shared MCP currently offers `academia_import_targets` and `academia_import_file` for an already-downloaded local file. The server cannot verify that the host showed a confirmation dialog, so each host must obtain explicit student confirmation of the exact file and destination before calling the write tool.

## Implementation stages

### Stage 1 — Shared tool contracts

**In progress.** The local MCP provides bounded context reads, exact inbox targets, a host-gated local-file import contract with processing status, executable-choice-validated Review decisions, separate execution for already-approved supported domain changes, and processing-status reads. It has no generated-document writer; saved practice goes through the Study interface. Activity attributes MCP-initiated actions to `agent:mcp`. Hosts still own the confirmation UI because the stdio server cannot prove that a human saw a prompt.

Remaining within this stage: ensure import/artefact actions have clear student confirmation in each compatible host and expose actionable Review workflows consistently.

### Stage 2 — In-app assistant host

**Partially implemented.** Study chat invokes the installed Codex CLI with bounded context and browser-local chat persistence. Proposal mode additionally uses the Codex app-server with `academia mcp serve --proposal-only`; task and import proposal grants are enabled independently, and the assistant cannot approve, execute, copy, or write. Browser proposal runs stream progress, expose a Stop control, and refresh proposal status from Review; task proposals can be edited before approval. Proposal summaries, statuses, and Review ids are saved with browser-local chat history. Settings provides an app-level ChatGPT device-code sign-in using Codex's official login flow; Academia never reads or stores credentials. The provider-neutral `RunController` now validates exact `ToolGrant` permissions and routes import/study/domain/task writes: approval-gated tools create Review items, create-only writes require host confirmation, and read tools remain scope-bound. The packaged Tauri shell still uses the non-streaming chat transport. Claude subscription routing is disabled pending an Anthropic-approved path. Still needed: native streaming/cancellation in Tauri, broader provider adapters using the shared grant loop, external MCP client connections, and per-tool grant management beyond chat proposal toggles. Do not imply current Study chat can call external tools.

### Stage 3 — Provider and connection management

**Partially implemented.** Study chat checks the local Codex CLI sign-in and offers model choices; Claude appears as unavailable with its Anthropic authorization reason. Settings now provides an app-level ChatGPT device-code sign-in through the official Codex app-server and reports the signed-in account summary without storing credentials. The app does not store provider secrets. Still needed: an MCP connection manager with explicit add, inspect, grant, disable, and disconnect flows. Start external services as read-only and verify each advertised integration against its actual tool list and granted scopes.

### Stage 4 — Integrations and automation

**Not implemented.** Add browser acquisition and Google services incrementally. Begin with visible portal read/download and read-only calendar/email/document access. Add calendar edits only through approval, duplicate checks, and verification. Never submit schoolwork or send school-account messages. Background jobs require a separate, visible opt-in and local audit trail.

## Completion criteria

- In-app assistant and external agents call the same structured Academia services.
- Every connected tool is shown with an accurate status and permission scope.
- User data and secrets remain local; a hosted provider receives only selected context for an explicit request.
- Imports preserve originals, record provenance, process locally, and report verified outcomes.
- Generated material remains create-only, source-linked where required, and non-authoritative.
- All supported writes have explicit user authorization, safe execution, verification, and Activity records.
- Disabling the assistant or disconnecting a service does not affect access to local academic files or workspaces.
