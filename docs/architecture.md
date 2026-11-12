# Architecture

## Runtime layers

```text
frontend/                         React + TypeScript student-facing UI
frontend/src-tauri/                optional Tauri 2 desktop shell
         │ typed command bridge
academia_os/                       agent-neutral core and CLI
├── config.py                      canonical v2 config + migrations
├── semester.py                    calendar-aware resolution
├── discovery.py                   workspace discovery
├── workspace.py                   rebuildable index/projection
├── library.py                     safe current-semester material inventory
├── agent.py                        bounded Agent Context, attention, changes, capabilities
├── recommendations.py              validated Agent Setup Playbook registry (legacy module name retained)
├── workflow_preferences.py          validated local student workflow overrides
├── provenance.py                  labels + source verification
├── review.py                      durable Review Queue
├── activity.py                    durable append-only activity
├── processing.py                  retryable inbox lifecycle
├── actions.py                     proposal/approval policy
├── workflow.py                    Review ↔ Action ↔ Activity coordination
├── state.py                       locked atomic JSON state primitives
├── acquisition.py                 manual/watched acquisition
├── browser.py                     browser-neutral metadata/policy
├── settings.py                    diff + safe update model
└── cli.py                         universal local interface
         │ optional adapters
adapters/
└── hermes/                        Hermes detection and translation only
installer/                         bootstrap, templates, migration, health audit
runtime/                           compatibility scripts copied into installations
desktop/                           legacy Tkinter compatibility frontend
templates/University/              readable academic workspace template
```

## Source of truth and projections

The user’s workspace remains the human-readable source of truth. `.academia/` is local structured state: rebuildable indexes, acquisition/provenance records, Review/Activity records, processing records, and proposals. Indexes can be rebuilt from the workspace; they are not a database dump that makes files inaccessible.

## Shared local core and two supported host paths

```text
IN-APP ACADEMIA ASSISTANT (target host)       CODEX / CLAUDE / OTHER EXTERNAL HOST
Conversation · provider choice · MCP clients   Conversation · provider/tool environment
                   \                                /
                    \                              /
                     ▼                            ▼
                 SHARED ACADEMIA INTERFACE
          Local context · evidence · provenance · Review
          safe imports · Study records
                              │
                              ▼
                    ACADEMIC WORKSPACE
       Human-readable originals · student material · structured Study records

DASHBOARD: visibility · browsing · status · Activity · Courses · Tasks · Settings
```

The local core remains the source of academic state and safety policy. The CLI/API and local stdio MCP are shared interfaces; they do not create a parallel academic database or expose `.academia` internals. Context is deliberately bounded by scope (`workspace`, `semester`, `course`, or `today`) and detail (`compact`, `standard`, or `deep`). It returns identifiers, workspace-relative paths, evidence references, and supported action information rather than dumping source contents. The `sources.library_items` catalog is metadata-only and covers syllabi, readings, lectures, assessments, notes, other material, inbox location, and processing status within the bounded scope. Retired `AI_GENERATED` document folders are excluded. Both a future in-app assistant and external agents should use these same contracts.

The local MCP currently exposes bounded reads, host-gated file import, structured Review decisions, and a separate executor for already-approved supported domain changes. It no longer exposes a generated-document writer. Study sets and practice are created through the Study interface. Review decisions must match an executable choice returned by `academia agent attention`; Activity identifies the caller as `agent:mcp`. The MCP server cannot verify that a human confirmation dialog was shown, so each compatible host must obtain confirmation of the exact choice and effect before calling a write tool. It does not connect to browser, email, calendar, or other external services. Dashboard Study chat can invoke the user's signed-in Codex CLI subscription, but its model tools are disabled and it is not an MCP client. Claude subscription OAuth cannot be routed through Academia under Anthropic's current restrictions; Claude Code remains usable as an external host. Full in-app MCP-client/tool orchestration remains planned. External Codex or another compatible host can connect to Academia MCP and its own separately authorized tools.

`academia agent playbooks --json` and `academia agent playbook PLAYBOOK_ID --json` expose the static Agent Setup Playbook registry. The registry separates implemented Academia capabilities from portable workflow guidance. Reading it is side-effect free: it does not inspect Gmail, calendars, course portals, browsers, research services, communities, or schedulers; it does not create integrations or store their state. External hosts use their own configured tools. A future in-app assistant may use user-enabled MCP connections, but it must report only services that are actually configured and authorized. The older `recommendations` and `recipe` commands remain compatibility aliases.

`academia workflow preferences --json`, `workflow show WORKFLOW_ID --json`, and `workflow set WORKFLOW_ID ... --json` expose the separate student-owned preference layer. `workflow_preferences.py` stores validated overrides, custom instructions, optional maintenance notes, timestamps, and audit attribution under `<academic_root>/.academia/workflow_preferences.json` through `JsonStateStore`. Reads do not create missing state; writes are atomic and locked. A show response includes the canonical Agent Setup Playbook, a compatibility recipe view, saved overrides, and merged effective preferences. The store rejects unknown playbook IDs, unknown preference keys, type mismatches, invalid times/timezones, unsupported attribution, and credential-like fields or notes. It does not contain fields such as provider-connected, account-connected, or automation-running, and saved preferences never authorize external access.

`attention.items` is the conversation-facing representation of unresolved Review decisions and retryable or advisory issues. `choices[]` is reserved for stable executable decisions and contains a structured Review action descriptor; `recommended_next_actions[]` is explicitly non-executable guidance. A supported linked domain-change decision can advertise the two-stage `review_decide` then `review_execute` flow. Processing retry and source verification are advisory until a backend executor exists. The agent asks the student in its own conversation and then uses the existing Review/Action/Verification workflow. The core does not store external agent conversations; dashboard Study chat has a separate client-side history store in browser IndexedDB.

`agent changes` reads append-only Activity oldest-first after an Activity ID or ISO timestamp cursor and returns a new cursor. Reusing the returned cursor is idempotent. Activity remains a record of changes the core actually performed, not reads or chat messages.

The separate generated-document artifact API has been removed. Study guides, quizzes, flashcards, and related practice are generated and saved as structured, cited Study sets through `academia study`; they remain non-authoritative student study records rather than standalone Library documents. Legacy files under `06_KNOWLEDGE/AI_GENERATED/` are excluded from Library and source discovery and have been removed from the configured three-course workspace.

`academia_os.config` is the only canonical configuration model. It owns schema version 3, defaults, validation, atomic serialization, and v1/v2 migration. The installer, CLI, desktop compatibility app, and adapters consume it. Hermes is an optional `agents.hermes` adapter section, not a required core path. Pre-playbook integration/automation values are moved to `legacy_compatibility` and are never fresh-install defaults.

The migration engine is also shared across interfaces. `installer/migration.py` creates a hash-verified, semester-aware plan, while `academia migration plan/status/execute` is the stable agent/Tauri contract. The React/Tauri migration view never reimplements routing: it selects items and sends explicit copy or confirmed-move commands to the CLI. Plans, reports, and Markdown review artifacts live under the runtime directory; the academic workspace remains the readable source of truth. Copy is the default, unknown material stays identifiable under `LEGACY_IMPORT`, and unsafe/operational paths are rejected.

Structural settings use `academia_os.settings.update_config()`, which returns a field-level diff and refuses root/runtime/semester changes unless explicitly approved. The desktop UI displays an impact summary before initializing missing structure.

## Reliability

`academia_os.processing.ProcessingStore` persists each source signature and lifecycle status. Supported manual imports launch a detached local worker that obtains a lease, extracts text, writes a rebuildable `.academia/extracted_sources.json` cache, verifies the source signature, and acknowledges the record. Failures retain a reason and can be retried. `academia process forget` removes only a failed record whose source is missing from a direct semester or course inbox, and records the cleanup in Activity. On macOS, scanned PDFs and common image files use local Apple Vision OCR through Swift, with page/text bounds and an explicit OCR verification warning. Other platforms without a configured local OCR provider report `unsupported_without_ocr`. The runtime inbox gate only detects/reports; it never acknowledges. Extraction preserves the source and does not interpret document instructions or update academic facts.

## Acquisition

Core acquisition normalizes manual files, watched-folder candidates, and browser metadata. Manual imports of PDF, DOCX, PPTX, plain text, Markdown, and common images start local extraction automatically; PPTX extraction reads visible slide text but does not OCR embedded images or include speaker notes. macOS uses Apple Vision for scanned PDFs and images. Browser implementations are adapters. Current supported browser behavior is limited to optional visible Chromium handoff; Firefox, Safari, and a companion extension remain planned. Browser access defaults off and should not read credentials or browser secrets.

## Agent, browser, and automation ownership

The shared core does not require a model. It owns the local workspace, structured state, provenance, processing lifecycle, Review Queue, Activity, and safety policy. Dashboard Study chat currently invokes the installed Codex CLI with selected context; when Proposal mode is enabled it uses the Codex app-server with Academia's local MCP server in proposal-only mode, so it can create exact task/import proposals only for the per-tool grants the student enables, and cannot approve, execute, or write. Browser proposal runs stream progress, support cancellation, refresh proposal status from Review, and allow task-proposal editing before approval; the packaged Tauri shell still uses the non-streaming transport. Settings provides an app-level ChatGPT device-code sign-in through Codex's official flow without Academia storing credentials. Its provider menu shows Claude as unavailable because Anthropic restricts subscription OAuth to Claude Code and other native Anthropic applications. Claude Code remains available as a separate external agent through the documented Academia interface. Provider-neutral assistant runs require exact `ToolGrant` permissions; MCP-client management and additional per-tool grant controls remain future work. External agents continue to use the same CLI/API/MCP and retain their own provider/tool configuration.

The browser flag is a defense-in-depth core guard: the current optional Chromium capability is a visible read-only handoff. It does not log into a school account or grant a host credentials. Any future in-app connector must be explicitly enabled and scoped, and it must not access credential/session data. The core has no independent recurring daemon; external automation remains separately configured and any resulting changes still pass through core action and approval rules.

## Agent Setup Playbook ownership

The nine shipped playbooks are product guidance, not integrations: Daily Academic Brief, Course Source Sync, Academic Library / Scholarly Research, Calendar Awareness, Academic Email Awareness, General Web Research, Community Research, Practice Material Discovery, and Visual / Media Learning Sources. They state desired outcomes, optional capability requirements, authorization choices, safety boundaries, provenance/authority expectations, and verification steps. An external agent decides whether it has the required tools, asks the student, adapts the mechanics, and reports what it actually configured. Academia OS never infers or stores external service status.

The Settings dashboard renders each playbook as an expandable guide plus a reusable My playbook preferences editor. The editor starts from `suggested_defaults`, supports common string, boolean, numeric, and array values, accepts custom instructions and optional notes for the implementing agent, and saves through the same `workflow set` command used by agents. It has no provider-connect or automation controls; the displayed prompt tells the student to ask an agent to use the saved preferences.

## Action safety

`ActionStore` represents proposed, approved, executed, verified, rejected, and failed actions. School submissions, school-account messaging, and authentication are hard-prohibited. Academia OS does not implement payments; agents must never infer payment authorization, and any future payment capability would require explicit student confirmation. Calendar, file, and configuration changes require explicit approval according to their policy.

## Optional Hermes boundary

Core code may run with no Hermes executable or home directory. `adapters/hermes/` translates neutral job descriptions only when configured. The old generated cron script remains a compatibility path for v1 Hermes-enabled profiles; it is not part of the core installation contract.

## Shared study domain

`academia_os/study/` implements a provider-independent study domain and course source retrieval. `study/cli.py` exposes the contract to external agents and the existing browser/Tauri bridge; `frontend/src/StudyView.tsx` is another client. `study/providers.py` optionally requests schema-constrained generation from the installed ChatGPT-authenticated Codex CLI or a loopback local model. Claude Code external agents may submit their own generated payload through `study create`; Academia does not route Claude subscription OAuth. Study sets, citation excerpts/fingerprints, sessions, responses, spaced-review state, annotations, preferences and exam scope are durable student-owned course records in `06_KNOWLEDGE/STUDY/study.json`, not rebuildable `.academia` caches. Activity remains shared. `agent context` includes bounded answer-free study summaries; `study context` retrieves selected source bodies explicitly. See [study.md](study.md).
