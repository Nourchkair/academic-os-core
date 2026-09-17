# Academic OS Core

Reusable local academic operating system for students. This repository contains the portable rules, blank University/course templates, parameterized runtime scripts, and a non-destructive onboarding wizard.

It does **not** contain anyone's academic files, browser profile, sessions, memories, OAuth tokens, passwords, API keys, Telegram/chat destinations, or live cron state.

## Quick start

From a clone of this repository:

```bash
python3 installer/bootstrap.py
```

The wizard asks for identity, institution, semester, local folder, preferences, and optional integration choices. It never asks for passwords, tokens, cookies, or MFA codes.

For a non-interactive setup, copy `config/manifest.example.json`, edit it, and run:

```bash
python3 installer/bootstrap.py --manifest /path/to/profile.json
python3 installer/verify.py /path/to/generated-install/profile.json
```

## What gets created

The bootstrapper creates two separated locations:

1. The user's academic root, such as `~/Desktop/University/`, containing blank rules, semester shell, and course template.
2. The user's local runtime directory, normally `~/.academic-os/`, containing the profile, parameterized scripts, generated cron specifications, and handoff guide.

Hermes integration files are copied into the configured Hermes home only when the user runs the bootstrapper. Existing differing files are never overwritten automatically.

## First-use workflow

1. Install or verify Hermes on the user's computer.
2. Run the bootstrapper.
3. Run the generated verification command.
4. Review `HANDOFF.md` and `generated_cron_jobs.json`.
5. Authorize Google services directly in the user's own browser/account.
6. Log into the school portal manually in the user's visible browser.
7. Add syllabi and initial course documents to confirmed course inboxes.
8. Run the generated local cron installer only after reviewing it.

## Runtime boundaries

- Original material is preserved before interpretation.
- Unknown course facts remain unknown instead of being invented.
- Calendar writes require user confirmation and duplicate checks.
- School-portal automation is read-only and bounded to acquisition/handoff.
- Credentials are handled by the user's own OAuth/browser flows, not by this repository.
- Generated summaries and dashboards are not citation endpoints.

## Desktop app

The repository also includes a native local desktop wrapper:

```bash
python3 desktop/app.py
```

It provides the friendly onboarding flow, folder discovery, automatic time-zone detection, local dashboard, course creation, verification, and quick links to the University folder and Hermes. On macOS, build a clickable app bundle with:

```bash
python3 desktop/build_macos_app.py
open 'dist/Academic OS.app'
```

The desktop app reuses the same installer/core and never stores credentials. See `desktop/README.md`.
