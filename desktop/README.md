# Desktop app

The desktop app is a native Tkinter wrapper around the same Academic OS core. It does not introduce a second database or a second configuration system.

## Run locally

From the repository root:

```bash
python3 desktop/app.py
```

For a headless health check:

```bash
python3 desktop/app.py --print-dashboard --profile ~/.academic-os/profile.json
```

## Build a clickable macOS app

On macOS:

```bash
python3 desktop/build_macos_app.py
open 'dist/Academic OS.app'
```

The bundle contains the reusable templates and installer but leaves personal data in the user's local `University` and `~/.academic-os` directories. It uses the recipient's installed Python 3 and does not embed credentials.

## What the app can do

- Find likely existing University/academic folders
- Explain why a folder was selected
- Browse for or create a local workspace
- Detect the computer's IANA time zone
- Offer friendly semester/time-zone choices
- Create or attach to an Academic OS workspace without overwriting differing files
- Show courses, inbox count, semester, and daily dashboard preview
- Open the local University folder and dashboard
- Add a course from the safe blank template
- Import older University material in a reviewable migration phase
- Find likely legacy folders without scanning the whole computer
- Preview semester-aware destinations before importing
- Select specific files, copy them safely, or explicitly move them after hash verification
- Open a migration plan for AI/human review without allowing direct AI moves
- Run installation verification
- Open Hermes in Terminal
- Show which integrations are prepared without claiming that authorization succeeded

## Migrating an older University folder

After creating a fresh workspace, open **Import older University material** from the dashboard. Choose or find the old folder, scan it, and review the exact destination of each file. The default action is **Copy selected safely**; the old folder remains intact. **Move selected** is explicit and removes only files whose copied destination hash matches the source hash. Existing destinations are never overwritten.

Semester names found in original folder paths are used only as routing evidence. Files with no clear semester are placed in the current semester's `00_INBOX/LEGACY_IMPORT` for review. The generated `migration/MIGRATION_REVIEW.md` can be opened for AI assistance, but AI must propose classifications rather than execute moves.
