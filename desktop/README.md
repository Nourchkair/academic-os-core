# Desktop applications

Academia OS now has two desktop surfaces:

1. **Modern frontend foundation** — React + TypeScript under `frontend/`, with a Tauri 2 shell and typed bridge to the universal `academia` CLI.
2. **Tkinter compatibility app** — `desktop/app.py`, retained while the modern shell reaches feature parity. It uses the same canonical config/core and is not authoritative over a second database.

## Modern frontend development

```bash
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

The browser preview intentionally shows a connection state if the local Tauri/CLI bridge is absent. It does not fabricate course data. The packaged shell calls the installed `academia` executable through a narrow allow-listed command bridge.

Native packaging is currently a development foundation. `frontend/src-tauri/tauri.conf.json` has `bundle.active: false`; signing, notarization, Python/CLI sidecar packaging, and release installers remain future work.

## Legacy compatibility app

From the repository root:

```bash
python3 desktop/app.py
python3 desktop/app.py --print-dashboard --profile ~/.academic-os/profile.json
```

It can still discover workspaces, create or attach safely, import legacy files through the migration phase, show the dashboard, edit local profile settings, and run health verification. Settings load the existing profile rather than starting from an empty wizard. Structural changes show a diff/impact confirmation and never silently rebuild or overwrite the workspace. The compatibility app does not configure Gmail, Calendar, Drive, Brightspace, browser sessions, or recurring jobs; its Agent Setup Playbooks panel points students to the local playbook/preferences contract and an authorized external agent.

## Development macOS bundle

```bash
python3 desktop/build_macos_app.py
open 'dist/Academic OS.app'
```

This is a lightweight development bundle around the local Python compatibility app. It does not require Hermes and does not embed credentials or academic data. The modern Tauri bundle is a separate path.

## Product views in the modern shell

- **Home** — today’s academic focus, open tasks, attention queue, courses, and recent activity.
- **Courses** — course state and intake/review signals rather than a raw folder tree.
- **Tasks** — structured work with source and confidence labels.
- **Library** — live, local inventory of readings, syllabi, notes, references, and imported material, with clickable category filters.
- **Review** — durable uncertain/approval-required items plus activity history.
- **Settings** — local profile/workspace settings and Agent Setup Playbooks; external accounts, browser sessions, permissions, and schedules remain outside Academia OS.
