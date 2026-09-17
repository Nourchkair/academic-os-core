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
