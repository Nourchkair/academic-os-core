# Architecture

```text
Reusable GitHub core
├── templates/University/          blank academic workspace
├── runtime/skills/                reusable Academic OS agent skill
├── runtime/scripts/               parameterized local automation
├── installer/core.py              manifest validation + safe generation
├── installer/migration.py         previewable copy/move migration engine
├── installer/bootstrap.py         interactive/non-interactive setup
├── installer/verify.py             post-install checks
└── desktop/                        native Tkinter UI + macOS app builder

Per-user local instance
├── University/                    private academic data
├── ~/.academic-os/                profile, scripts, jobs, state references
└── ~/.hermes/                     user-authorized Hermes runtime/integrations
```

The repository is the source of reusable behavior. The generated instance is the source of personal configuration. Existing personal files are never overwritten by the bootstrapper. The desktop app calls the same installer/model functions rather than introducing a second state store.

## Migration model

A fresh workspace can import material from an explicitly selected legacy folder. The migration engine records hashes and proposed destinations in `~/.academic-os/migration/`, uses semester names only when they appear in the source path, routes unknown items to current-semester `00_INBOX/LEGACY_IMPORT`, copies by default, and verifies every copy before an explicit move. AI can review the generated plan but cannot perform the move itself.

## Cron model

The bootstrapper generates two local-only Hermes job definitions:

- Daily Brief: reads the current academic root and writes the active semester dashboard.
- Inbox Processor: runs the cheap metadata gate before asking the agent to process changed inbox files.

The generated `install_cron.sh` is intentionally separate from initialization so the recipient can review schedules and paths before enabling them.
