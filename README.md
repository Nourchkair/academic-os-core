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

## Development checks

```bash
python3 -m pytest tests/ -q
python3 -m compileall installer runtime
```

The project has no runtime dependency beyond Python 3.11+; `pytest` is only needed for development tests.
