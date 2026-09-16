# Integration Status

Generated for **{{STUDENT_NAME}}** at **{{INSTITUTION}}**.

This file records the local installation state only. It must never contain passwords, OAuth tokens, browser cookies, or API keys.

## Local filesystem

- Academic root: `{{ACADEMIC_ROOT}}`
- Status: created by the local bootstrap wizard; verify with `installer/verify.py`.

## Gmail

- Requested: configure according to the generated profile.
- Status: not claimed until the user's own Google account authorization is completed and tested.
- Safety: read-only intake by default; no email is sent, deleted, archived, or modified without approval.

## Google Calendar

- Requested: configure according to the generated profile.
- Status: not claimed until the user's own Google account authorization is completed and tested.
- Safety: search for equivalent events before writes; no duplicates or deletions without explicit approval.

## Google Drive

- Requested: configure according to the generated profile.
- Status: not claimed until the user's own Google account authorization is completed and tested.

## School portal/browser

- Portal: {{SCHOOL_PORTAL}}
- Status: manual user login and real-profile/browser verification required.
- Safety: the system does not request, type, store, or record passwords, MFA codes, cookie values, or session secrets. It does not submit assignments, answer quizzes, post messages, or modify portal content.

## Automation

- Daily brief: generated local job; not enabled until reviewed.
- Inbox processor: generated local gate/job; not enabled until reviewed.
- Delivery: local only. No builder messaging account or chat destination is copied.
