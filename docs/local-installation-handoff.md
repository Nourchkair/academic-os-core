# Local installation handoff

This installation belongs to **{{STUDENT_NAME}}** at **{{INSTITUTION}}**.

## Generated locations

- Academic root: `{{ACADEMIC_ROOT}}`
- Academia OS runtime: `{{INSTALL_ROOT}}`
- Optional Hermes home: `{{HERMES_HOME}}`
- Semester shell: `{{ACADEMIC_ROOT}}/{{SEMESTER}}`
- Time zone: `{{TIMEZONE}}`

The academic workspace is human-readable and remains usable without Academia OS or any AI agent.

## Desktop entry points

Modern frontend development:

```bash
cd frontend
npm install
npm run typecheck
npm run build
```

Compatibility app:

```bash
python3 desktop/app.py
```

The setup/settings screen loads the existing profile when present. It does not silently recreate the workspace. Structural changes show an impact summary first.

## Required manual steps

1. Verify the local installation:

   ```bash
   python3 installer/verify.py {{INSTALL_ROOT}}/profile.json
   ```

2. Review the profile and generated job specifications. Hermes scheduling is optional and should only be enabled if the user explicitly wants the Hermes adapter.
3. Authorize selected Google services directly in the user’s own account, if enabled. Never send credentials to the builder or an agent.
4. Log into any school site manually in the user’s chosen browser profile. Browser access is optional and read-only.
5. Add authoritative course material only after confirming the course identity.
6. Keep original syllabi, instructions, rubrics, and other academic sources preserved.

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

## Optional automation

Academia OS core exposes local job specifications and the retryable inbox lifecycle. If Hermes is explicitly enabled, the optional adapter can translate those specifications into Hermes commands. No core workflow requires Hermes, cron, a messaging platform, or a school account.

## Important boundaries

- This installation starts with no invented courses or deadlines.
- Google and school-portal access belong to the recipient.
- The school-portal helper is read-only and does not submit work, answer quizzes, post messages, or modify settings.
- Do not place passwords, OAuth tokens, cookies, or API keys in the University directory or Git repository.
- Template upgrades must be reviewed as migrations; do not overwrite personal academic files.
