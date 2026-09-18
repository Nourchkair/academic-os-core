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

2. Review the generated Agent Setup Playbooks and local workflow-preference record. Academia OS does not configure external accounts or start recurring schedules.
3. If desired, ask an authorized external agent to implement a selected playbook. The agent must request Gmail/email, Calendar, Drive, course-platform/browser, or scheduler permissions through its own authorization flow and report what was actually configured and verified.
4. Add authoritative course material only after confirming the course identity.
5. Keep original syllabi, instructions, rubrics, and other academic sources preserved.

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

The same flow is available from the neutral CLI when an agent or script is authorized to use the local interface:

```bash
academia migration plan /path/to/old-university-folder --json
academia migration execute --plan {{INSTALL_ROOT}}/migration/migration-plan.json --item 0 --mode copy --apply --json
```

The plan path and runtime directory are local operational state. Agents may inspect and suggest, but file changes still require the explicit `--apply` command; Move additionally requires `--confirm-move`.

## External-agent-owned workflows

Academia OS exposes local capabilities, Agent Setup Playbooks, and saved student preferences. It does not create or own a recurring Daily Brief scheduler. An authorized external agent may translate a selected playbook into its own scheduler or tools after student approval. No core workflow requires Hermes, cron, a messaging platform, or a school account.

## Important boundaries

- This installation starts with no invented courses or deadlines.
- Google/email, Calendar, Drive, course-platform, browser, and scheduler access belong to the student's authorized external agent, if they choose one.
- Any school-platform workflow is read-only and does not submit work, answer quizzes, post messages, or modify settings.
- Do not place passwords, OAuth tokens, cookies, MFA codes, or API keys in the University directory or Git repository.
- Template upgrades must be reviewed as migrations; do not overwrite personal academic files.
