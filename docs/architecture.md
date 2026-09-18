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
├── artifacts.py                    create-only AI-generated secondary material + registry
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

The user’s workspace remains the human-readable source of truth. `.academia/` is local structured state: rebuildable indexes, acquisition/provenance records, generated-artifact registry, review/activity records, processing records, and proposals. Indexes can be rebuilt from the workspace; they are not a database dump that makes files inaccessible.

## AI-native operating boundary

```text
AI AGENT
Reasoning · conversation · teaching · writing assistance · planning · research synthesis
                                      │
                                      ▼
ACADEMIA OS
Academic state · bounded Agent Context · evidence · provenance · permissions
Review protocol · safe actions · generated artifacts · Activity audit trail
                                      │
                                      ▼
ACADEMIC WORKSPACE
Human-readable originals · student material · AI-generated secondary material

DASHBOARD
Observability · visual reference · browsing · status · Activity · Courses · Tasks
Files · Settings · import/migration
```

The agent interface is the primary product interface for authorized automation. `academia agent context`, `attention`, `changes`, and `capabilities` compose existing services; they do not create a parallel database or expose `.academia` internals. Context is deliberately bounded by scope (`workspace`, `semester`, `course`, or `today`) and detail (`compact`, `standard`, or `deep`). It returns identifiers, workspace-relative paths, evidence references, and safe-write locations rather than dumping source contents. The `sources.library_items` catalog is metadata-only and covers syllabi, readings, notes, generated material, and relevant imports within the bounded scope.

`academia agent playbooks --json` and `academia agent playbook PLAYBOOK_ID --json` expose the static Agent Setup Playbook registry. The registry separates Academia capabilities from portable external-agent guides. Reading it is side-effect free: it does not inspect Gmail, calendars, course portals, browsers, research services, communities, or schedulers; it does not create integrations or store their state. External agents own implementation mechanics, and students authorize any external access or automation. The older `recommendations` and `recipe` commands remain compatibility aliases.

`academia workflow preferences --json`, `workflow show WORKFLOW_ID --json`, and `workflow set WORKFLOW_ID ... --json` expose the separate student-owned preference layer. `workflow_preferences.py` stores validated overrides, custom instructions, optional maintenance notes, timestamps, and audit attribution under `<academic_root>/.academia/workflow_preferences.json` through `JsonStateStore`. Reads do not create missing state; writes are atomic and locked. A show response includes the canonical Agent Setup Playbook, a compatibility recipe view, saved overrides, and merged effective preferences. The store rejects unknown playbook IDs, unknown preference keys, type mismatches, invalid times/timezones, unsupported attribution, and credential-like fields or notes. It does not contain fields such as provider-connected, account-connected, or automation-running, and saved preferences never authorize external access.

`attention.items` is the conversation-facing representation of unresolved Review decisions and retryable or advisory issues. `choices[]` is reserved for stable executable decisions and contains a structured Review action descriptor; `recommended_next_actions[]` is explicitly non-executable guidance. A supported linked domain-change decision can advertise the two-stage `review_decide` then `review_execute` flow. Processing retry and source verification are advisory until a backend executor exists. The agent asks the student in its own conversation and then uses the existing Review/Action/Verification workflow. Academia does not store the conversation.

`agent changes` reads append-only Activity oldest-first after an Activity ID or ISO timestamp cursor and returns a new cursor. Reusing the returned cursor is idempotent. Activity remains a record of changes the core actually performed, not reads or chat messages.

`artifacts.py` owns the safe generated-material boundary. `academia artifact create` can write only Markdown under a recognized course’s lazy `06_KNOWLEDGE/AI_GENERATED/` directory. Each record is `AI-GENERATED`, `authoritative: false`, source-linked when the kind is source-derived, and stored in `.academia/artifacts.json` for library/dashboard visibility. Course identifiers accept the canonical ID, code, or exact course/display name. Source references are validated structurally: a course subtree records its actual course ID, a semester-level `00_INBOX` source records `course_id: null`, and files outside recognized academic locations are rejected. There is no arbitrary destination, original-file overwrite, or create/update ambiguity. This pass intentionally implements create-only semantics.

`academia_os.config` is the only canonical configuration model. It owns schema version 3, defaults, validation, atomic serialization, and v1/v2 migration. The installer, CLI, desktop compatibility app, and adapters consume it. Hermes is an optional `agents.hermes` adapter section, not a required core path. Pre-playbook integration/automation values are moved to `legacy_compatibility` and are never fresh-install defaults.

The migration engine is also shared across interfaces. `installer/migration.py` creates a hash-verified, semester-aware plan, while `academia migration plan/status/execute` is the stable agent/Tauri contract. The React/Tauri migration view never reimplements routing: it selects items and sends explicit copy or confirmed-move commands to the CLI. Plans, reports, and Markdown review artifacts live under the runtime directory; the academic workspace remains the readable source of truth. Copy is the default, unknown material stays identifiable under `LEGACY_IMPORT`, and unsafe/operational paths are rejected.

Structural settings use `academia_os.settings.update_config()`, which returns a field-level diff and refuses root/runtime/semester changes unless explicitly approved. The desktop UI displays an impact summary before initializing missing structure.

## Reliability

`academia_os.processing.ProcessingStore` persists each source signature and lifecycle status. Detection creates `PENDING` work; processing obtains a lease; verification must succeed before acknowledgement. Failures retain a reason and can be retried. The runtime inbox gate only detects/reports; it never acknowledges.

## Acquisition

Core acquisition normalizes manual files, watched-folder candidates, and browser metadata. Browser implementations are adapters. Current supported browser behavior is limited to optional visible Chromium handoff; Firefox, Safari, and a companion extension remain planned. Browser access defaults off and should not read credentials or browser secrets.

## Agent, browser, and automation ownership

The core does not contain a model or require an AI agent. It owns the local workspace, structured state, provenance, processing lifecycle, Review Queue, activity, and safety policy. External agents use the neutral CLI/API and own their own model, credentials, operating-system permissions, browser session, and schedule.

The browser flag is a defense-in-depth core guard: an adapter must still be explicitly allowed by the local policy before requesting read-only browser access. It does not launch a browser, log into a school account, or grant an agent credentials. The core has no independent recurring daemon; automation is adapter/scheduler-owned and any resulting changes still pass through core action and approval rules.

## Agent Setup Playbook ownership

The nine shipped playbooks are product guidance, not integrations: Daily Academic Brief, Course Source Sync, Academic Library / Scholarly Research, Calendar Awareness, Academic Email Awareness, General Web Research, Community Research, Practice Material Discovery, and Visual / Media Learning Sources. They state desired outcomes, optional capability requirements, authorization choices, safety boundaries, provenance/authority expectations, and verification steps. An external agent decides whether it has the required tools, asks the student, adapts the mechanics, and reports what it actually configured. Academia OS never infers or stores external service status.

The Settings dashboard renders each playbook as an expandable guide plus a reusable My playbook preferences editor. The editor starts from `suggested_defaults`, supports common string, boolean, numeric, and array values, accepts custom instructions and optional notes for the implementing agent, and saves through the same `workflow set` command used by agents. It has no provider-connect or automation controls; the displayed prompt tells the student to ask an agent to use the saved preferences.

## Action safety

`ActionStore` represents proposed, approved, executed, verified, rejected, and failed actions. School submissions, school-account messaging, and authentication are hard-prohibited. Academia OS does not implement payments; agents must never infer payment authorization, and any future payment capability would require explicit student confirmation. Calendar, file, and configuration changes require explicit approval according to their policy.

## Optional Hermes boundary

Core code may run with no Hermes executable or home directory. `adapters/hermes/` translates neutral job descriptions only when configured. The old generated cron script remains a compatibility path for v1 Hermes-enabled profiles; it is not part of the core installation contract.
