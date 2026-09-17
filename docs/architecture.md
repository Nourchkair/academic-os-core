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

The user’s workspace remains the human-readable source of truth. `.academia/` is local structured state: indexes, review/activity records, processing records, and proposals. Indexes can be rebuilt from the workspace; they are not a database dump that makes files inaccessible.

## Configuration

`academia_os.config` is the only canonical configuration model. It owns schema version 2, defaults, validation, atomic serialization, and v1 migration. The installer, CLI, desktop compatibility app, and adapters consume it. Hermes is an optional `agents.hermes` section, not a required core path.

Structural settings use `academia_os.settings.update_config()`, which returns a field-level diff and refuses root/runtime/semester changes unless explicitly approved. The desktop UI displays an impact summary before initializing missing structure.

## Reliability

`academia_os.processing.ProcessingStore` persists each source signature and lifecycle status. Detection creates `PENDING` work; processing obtains a lease; verification must succeed before acknowledgement. Failures retain a reason and can be retried. The runtime inbox gate only detects/reports; it never acknowledges.

## Acquisition

Core acquisition normalizes manual files, watched-folder candidates, and browser metadata. Browser implementations are adapters. Current supported browser behavior is limited to optional visible Chromium handoff; Firefox, Safari, and a companion extension remain planned. Browser access defaults off and should not read credentials or browser secrets.

## Action safety

`ActionStore` represents proposed, approved, executed, verified, rejected, and failed actions. School submissions, school-account messaging, payments, and authentication are hard-prohibited. Calendar, file, and configuration changes require explicit approval according to their policy.

## Optional Hermes boundary

Core code may run with no Hermes executable or home directory. `adapters/hermes/` translates neutral job descriptions only when configured. The old generated cron script remains a compatibility path for v1 Hermes-enabled profiles; it is not part of the core installation contract.
