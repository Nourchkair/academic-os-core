# Architecture

```text
Reusable GitHub core
├── templates/University/          blank academic workspace
├── runtime/skills/                reusable Academic OS agent skill
├── runtime/scripts/               parameterized local automation
├── installer/core.py              manifest validation + safe generation
├── installer/bootstrap.py         interactive/non-interactive setup
└── installer/verify.py             post-install checks

Per-user local instance
├── University/                    private academic data
├── ~/.academic-os/                profile, scripts, jobs, state references
└── ~/.hermes/                     user-authorized Hermes runtime/integrations
```

The repository is the source of reusable behavior. The generated instance is the source of personal configuration. Existing personal files are never overwritten by the bootstrapper.

## Cron model

The bootstrapper generates two local-only Hermes job definitions:

- Daily Brief: reads the current academic root and writes the active semester dashboard.
- Inbox Processor: runs the cheap metadata gate before asking the agent to process changed inbox files.

The generated `install_cron.sh` is intentionally separate from initialization so the recipient can review schedules and paths before enabling them.
