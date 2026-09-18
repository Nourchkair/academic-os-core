# AGENTS.md — Academia OS workspace guidance

This folder is a local Academia OS academic workspace. It remains readable and usable without Academia OS or any AI agent.

## Read first

- `ACADEMIC_OS_RULES.md` — safety, provenance, confidence, source verification, and academic-integrity boundaries.
- `INTEGRATION_STATUS.md` — local capability and saved playbook-intent status; it never claims that an external account or automation is connected.
- `VERIFICATION.md` — health checks and evidence.
- `{{SEMESTER}}/` — the active semester shell and course folders.

## Structured local interface

If the Academia OS CLI is installed, prefer these commands over reverse-engineering Markdown:

```text
academia status --json
academia courses --json
academia course "COURSE ID" --json
academia today --json
academia tasks --json
academia review --json
academia inbox --json
academia activity --json
```

Rebuildable indexes and workflow state live under `.academia/`. The underlying academic files remain the source of truth.

## Safety

- Preserve originals and provenance. Do not casually overwrite, delete, move, or rename academic material.
- Use confidence labels: `current-confirmed`, `likely`, `unverified`, `historical`.
- Use provenance labels: `ORIGINAL`, `USER-CREATED`, `AI-GENERATED`, `EXTERNAL`.
- Never invent courses, deadlines, readings, editions, grades, or institutional facts.
- Uncertain information and approval-required changes belong in the Review Queue.
- Calendar changes, structural changes, moves, and destructive actions require explicit user approval.
- Never submit academic work, send school-account messages, or authenticate as the user.
- Academia OS does not implement payments. Agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.
- Never read or store passwords, MFA codes, browser cookies, session tokens, or hidden secrets.

## Acquisition

Manual import and watched folders are supported without browser access. Browser access defaults off and is optional. The user chooses the browser/profile; a dedicated profile is recommended but not required. Current Chromium behavior is limited to optional visible handoff. Firefox, Safari, and browser-companion adapters are future work and must not be claimed as connected.

For sources, prefer legitimate library, institutional, publisher, DOI/open-access, repository, or author-released access. Verify requested editions. If legality or authorization is unclear, do not download or cite the copy.

## Agents

Hermes is optional. Codex, Claude, ChatGPT/Work, and future agents may use the same interface when authorized, but no agent is allowed to bypass the workspace safety rules or perform prohibited school/account actions.
