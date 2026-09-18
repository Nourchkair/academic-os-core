# Local capability and playbook status

Generated for **{{STUDENT_NAME}}** at **{{INSTITUTION}}**.

This file describes the local Academia OS installation and saved workflow intent only. It is **not** an account-connection report. It must never contain passwords, OAuth tokens, browser cookies, MFA codes, or API keys.

## Academia OS capabilities

- Academic root: `{{ACADEMIC_ROOT}}`
- Local workspace, provenance, imports, processing, Review, Activity, and safety boundaries are available on this computer.
- Manual import and local watched-folder scans do not require an external account.
- Browser access is off by default and limited to the documented read-only visible handoff when an external agent is authorized to use it.

## Agent Setup Playbooks

Desired workflows are described by the local Agent Setup Playbook registry and student-owned workflow preferences. The Daily Academic Brief preferences live in the `daily_academic_brief` playbook and `.academia/workflow_preferences.json` layer.

Saving a playbook preference does not connect an account, grant permission, start a scheduler, or prove that an external workflow is running.

## External-agent-owned capabilities

An authorized external agent may, with the student's separate approval, evaluate and implement optional Gmail/email awareness, calendar awareness, Drive/file access, course-platform/browser access, research services, delivery, or recurring scheduling using its own tools and authorization flow. Academia OS does not own those accounts, credentials, sessions, or automations.

The current safety contract remains absolute: no coursework, quiz, exam, form, discussion, or school-account message submission; no school-account messaging; no password/MFA/cookie/session handling. Academia OS does not implement payments; agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.

## Verification

Verify the local installation with `installer/verify.py`. Verify any external agent setup through that agent's own report, including what was configured, what was authorized, what was verified, what was unavailable, and what remains manual.
