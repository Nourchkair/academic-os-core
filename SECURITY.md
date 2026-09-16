# Security and privacy

## Never commit

- `.env` files containing secrets
- OAuth tokens or credential caches
- Browser profiles, cookies, session databases, or MFA data
- Personal academic folders or exported course files
- Hermes sessions, memory, logs, state databases, or live cron files
- User-specific chat IDs, email addresses, API keys, or connection strings

## Authorization boundary

The recipient authorizes Google services in their own browser/account. School-portal access is completed manually in the recipient's visible browser. The wizard does not request or store passwords, MFA codes, cookies, OAuth tokens, or API keys.

## Local data boundary

The generated University directory is personal data. Keep it outside this repository unless the user deliberately creates a separate private backup repository. The generated runtime directory is also personal and should not be committed.

## Safe update behavior

The bootstrapper refuses to overwrite differing files. Template updates must be reviewed and applied as migrations; they must not replace personal notes, original sources, drafts, submissions, grades, or generated course history.

## Reporting a problem

Do not paste secrets into GitHub issues or chat. Redact paths that reveal personal identities when sharing logs. Report the affected version and a minimal reproduction instead.
