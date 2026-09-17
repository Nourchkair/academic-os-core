# Local installation handoff

This installation belongs to **{{STUDENT_NAME}}** at **{{INSTITUTION}}**.

## Generated locations

- Academic root: `{{ACADEMIC_ROOT}}`
- Academic OS runtime: `{{INSTALL_ROOT}}`
- Hermes home: `{{HERMES_HOME}}`
- Semester shell: `{{ACADEMIC_ROOT}}/{{SEMESTER}}`
- Time zone: `{{TIMEZONE}}`

## Desktop app

If you received the repository, the easiest entry point is:

```bash
python3 desktop/app.py
```

On macOS, a clickable application can be built with:

```bash
python3 desktop/build_macos_app.py
open 'dist/Academic OS.app'
```

The app's setup screen can look for an existing University folder, detect the computer's time zone, create or attach to a workspace, and show the local dashboard. It uses the same bootstrapper and verification logic described below.

## Required manual steps

1. Verify the folder structure with:

   ```bash
   python3 installer/verify.py {{INSTALL_ROOT}}/profile.json
   ```

2. Review `{{INSTALL_ROOT}}/generated_cron_jobs.json` and `{{INSTALL_ROOT}}/install_cron.sh`.
3. Authorize selected Google services directly in the user's own account. Do not send credentials to the builder.
4. Log into `{{SCHOOL_PORTAL}}` manually in the user's visible browser if the school-portal workflow is enabled.
5. Add authoritative course material only after confirming the course identity.
6. Keep original syllabi, instructions, rubrics, and submissions preserved.

## Migration phase

If the recipient wants a fresh folder but has older University material, use **Import older University material** from the desktop dashboard. The migration phase:

- Finds or browses to the old folder explicitly.
- Produces a file-by-file preview and a saved JSON/Markdown plan.
- Routes confirmed semester paths to that semester, current-semester material to `00_INBOX/LEGACY_IMPORT`, and unknown material to the current-semester intake area.
- Lets the user select specific files.
- Copies by default and leaves the legacy folder unchanged.
- Offers an explicit move only after verifying the copied file hash.
- Never overwrites an existing destination; collision copies receive a suffix.
- Opens an AI-reviewable plan, but does not let an AI conversation execute file moves.

To do nothing, close the migration window. The old folder remains available.

## Enabling local automation

After review, run:

```bash
sh {{INSTALL_ROOT}}/install_cron.sh
```

The generated commands use local delivery only. They do not copy the builder's Telegram, email, account, or chat destination.

## Important boundaries

- This installation starts with no invented courses or deadlines.
- Google and school-portal access belong to the recipient.
- The school-portal helper is read-only and does not submit work, answer quizzes, post messages, or modify settings.
- Do not place passwords, OAuth tokens, cookies, or API keys in the University directory or Git repository.
- Template upgrades must be reviewed as migrations; do not overwrite personal academic files.
