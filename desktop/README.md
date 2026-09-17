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
- Run installation verification
- Open Hermes in Terminal
- Show which integrations are prepared without claiming that authorization succeeded

## Safety behavior

The app never asks for passwords, OAuth tokens, browser cookies, or MFA codes. Existing non-Academic-OS folders are not modified automatically. Existing Academic OS folders can be attached in missing-file-only mode; differing personal files remain untouched and are never overwritten.
