# Optional school-site acquisition reference

This reference applies only when the user explicitly enables a supported acquisition adapter. Academia OS does not require school-site access.

## Preferred acquisition levels

1. **Manual import** — the user downloads/selects the file; Academia OS stages a copy for review and keeps the original.
2. **Watched folder** — the user configures a local folder such as `Downloads/School`; new files enter the retryable intake flow.
3. **Browser companion** — planned. It should expose explicit actions such as `Send to Academia OS`, `Save reading`, `Add course page`, and `Import this file/page`.
4. **Advanced browser adapter** — optional, off by default, and limited by an explicit user-selected profile and site allow-list.

## Safe sequence for any implemented browser adapter

1. Resolve the exact course folder and inspect its local context/rules.
2. Confirm the configured browser access policy is enabled and the requested site matches the explicit allow-list.
3. Let the user authenticate manually if authentication is needed. Never ask for, type, store, or record passwords, MFA codes, cookies, or session tokens.
4. Verify the rendered page itself contains the exact institution/course/code/semester/module requested. A login page or generic URL is not evidence of access.
5. Snapshot the relevant local download folder before acquisition and compare after. Only newly created or changed files from the explicit user action may be staged.
6. Preserve originals, hash-check copies, avoid overwrites, and record normalized metadata: source type, browser/profile label, source URL, acquired-at timestamp, original file, and verification outcome.
7. Leave ambiguous material in intake/review. Do not invent a course, deadline, edition, or source identity.

## Browser support status

- Manual file import: supported.
- Watched folders: supported.
- Chromium-family visible handoff: optional supported adapter boundary.
- Firefox automation: planned, not implemented.
- Safari automation: planned, not implemented.
- Browser companion extension: planned, not implemented.

School sites remain read-only. No adapter may submit work, answer quizzes, post messages, change settings, delete content, unenroll, or alter account settings.
