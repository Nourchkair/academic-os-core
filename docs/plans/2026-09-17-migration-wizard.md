# React/Tauri Legacy Migration Wizard Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Expose the existing copy-first, hash-verified migration engine through the neutral Academia CLI and make it usable from the primary React/Tauri desktop interface.

**Architecture:** Keep `installer/migration.py` as the single migration engine. Add a thin CLI contract that stores reviewable plans and reports under the configured runtime directory, validates plans against the active workspace, and requires explicit apply/move confirmation. Add a React migration view and Tauri bridge calls that consume only the CLI JSON contract; do not move academic files or duplicate routing logic in TypeScript.

**Tech Stack:** Python 3.11+, pytest, existing `academia_os` CLI, React/TypeScript, Tauri 2, existing dialog plugin.

---

### Task 1: Add migration plan persistence and CLI contract tests

**Objective:** Define the machine-readable `migration plan`, `migration status`, and `migration execute` behavior through failing tests before implementation.

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_migration.py` if reusable plan round-trip coverage belongs there

**Contract:**
- `academia migration plan /old/folder --json` creates a reviewable plan under the configured runtime migration directory and returns the plan plus `plan_path`, `review_path`, and summary fields.
- `academia migration status --plan /path/to/migration-plan.json --json` returns plan/report status without changing academic files.
- `academia migration execute --plan /path/to/migration-plan.json --item INDEX ... --mode copy --apply --json` copies selected items only after explicit apply.
- `--mode move` requires both `--apply` and `--confirm-move`.
- The active profile workspace must match the plan's `academic_root`; invalid or out-of-range item selections fail closed.
- A preview or status call is read-only.

**Verification:** Run focused tests and observe the new tests fail because the commands do not exist.

### Task 2: Implement the neutral migration CLI facade

**Objective:** Add plan serialization/loading and CLI dispatch while reusing `installer.migration` for all routing and file operations.

**Files:**
- Modify: `installer/migration.py`
- Modify: `academia_os/cli.py`
- Modify: `tests/test_cli.py`, `tests/test_migration.py`

**Safety requirements:**
- Validate source and destination roots on load.
- Never accept `.academia`, the active workspace itself, or a plan targeting another workspace.
- Preserve collision-safe naming and SHA-256 verification.
- Store the latest execution report beside the plan.
- Keep the original source untouched in copy mode.

**Verification:** Focused CLI/migration tests pass, then full Python suite passes.

### Task 3: Add frontend bridge types and Tauri command allow-list support

**Objective:** Make the new CLI contract available to React through the existing `academia_command` bridge.

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src-tauri/src/lib.rs`

**Verification:** Typecheck passes and the bridge rejects no valid `migration` command.

### Task 4: Build the React/Tauri migration view

**Objective:** Provide a primary desktop migration surface with safe defaults and explicit review controls.

**Files:**
- Create: `frontend/src/MigrationView.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/Onboarding.tsx` if a post-setup migration entry point is added

**UX requirements:**
- Browse for an old folder using the existing Tauri dialog plugin.
- Generate a read-only plan before any copy.
- Show file count, total size, semester routing, source path, and proposed destinations.
- Allow select-all/clear-all and per-item selection.
- Copy is the default action.
- Move is visibly destructive and requires an additional confirmation step.
- Show success, partial failure, and no-file states.
- Show that the old folder remains unchanged in copy mode.
- Link users to Review when uncertain items need later classification.

**Verification:** Frontend lint, typecheck, build, and a deterministic component-level test or contract harness pass.

### Task 5: Add end-to-end migration journey coverage

**Objective:** Prove the CLI and UI-facing contract supports fresh setup followed by selective legacy migration without touching the source.

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_migration.py`
- Add frontend contract tests only if the repository's existing frontend test harness supports them

**Verification:** Exercise plan → selected copy → report/status → source preservation → collision handling → explicit move gate.

### Task 6: Review, document, and publish

**Objective:** Verify the complete change and document exact behavior and limits.

**Files:**
- Modify: `README.md`
- Modify: `docs/local-installation-handoff.md`
- Modify: `docs/architecture.md`

**Verification:**
- Independent spec and quality review.
- `python3 -m pytest tests/ -rA`
- `python3 -m compileall -q academia_os installer desktop adapters runtime scripts`
- `cd frontend && npm run lint && npm run typecheck && npm run build`
- `git diff --check`
- Privacy scan and exact-head CI verification.
- Do not access the protected live workspace during testing.
