# Security and academic safety

Academia OS is local-first. Its core remains useful without an agent, browser automation, or school account access.

## Non-negotiable boundaries

- Preserve original academic files and provenance.
- Never casually overwrite, delete, rename, or move academic material.
- Keep `current-confirmed`, `likely`, `unverified`, and `historical` distinctions visible.
- Keep `ORIGINAL`, `USER-CREATED`, `AI-GENERATED`, and `EXTERNAL` provenance visible.
- Never submit academic work or send school-account messages.
- Academia OS does not implement payments. Agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.
- Never authenticate as the user.
- Never read or store passwords, MFA codes, cookies, session tokens, or hidden API keys.
- School websites are read-only in the current implementation.
- Calendar changes and destructive/structural changes require explicit user approval.
- Do not invent courses, deadlines, readings, versions, or institutional facts.

## Browser privacy

Browser access is optional and defaults off. Manual import and watched folders are fully supported without it. The user chooses the browser and profile; “school browser account” is not a required concept. A dedicated profile is recommended to reduce unrelated browser information visible to an optional adapter, but it is not required and does not guarantee complete isolation.

The current Chromium capability is limited to explicit visible handoff. Firefox and Safari are planned adapters, not implemented integrations. Domain allow-lists reduce intended scope but do not guarantee isolation against all browser capabilities.

## Source legality and verification

Prefer university library, Omni/OpenAthens, publisher, DOI/open-access, institutional repository, or author-released sources. Discovery-only results do not authorize downloading unclear copies. Academia OS does not implement payments; agents must never infer payment authorization. Any future payment capability would require explicit student confirmation. Verify that a retrieved source matches the requested edition and retain `EXACT MATCH — HIGH CONFIDENCE`, `PROBABLE MATCH — VERIFY MANUALLY`, `MISMATCH`, or `NOT RETRIEVED` outcomes.

## Verification scopes

System health checks validate configuration, workspace structure, index readability, runtime scripts, core modules, and processing state. It must not fail merely because a private workspace contains a normal email address or local path.

Safe-to-share auditing is separate and flags emails, local paths, credentials, tokens, and private account information before a user exports or publishes a folder.

## Reporting vulnerabilities

Do not include private academic files, profile JSON, browser state, tokens, or personal paths in public issues. Use the repository’s private security-reporting process when one is configured, and provide a minimal reproducible description.
