# Keychain ownership and clean-install checks

Academia OS stores secrets in the macOS login Keychain. The goal is that a
normal user connects Google or an API provider without having to understand
Keychain, and without repeated password prompts.

## Ownership rules

- The signed `academia` sidecar is the only process that reads or writes Google
  tokens and model-provider API keys.
- The Tauri UI asks the sidecar for status; it never reads secrets directly.
- The Google OAuth client ID and secret are bundled in the packaged sidecar.
  Packaged builds do not read the legacy Google client item from Keychain.
- Keychain stores only user tokens (Google, Notion, remote MCP) and user-supplied API model keys.
- No secret is written to `profile.json`, workflow preferences, the academic
  workspace, logs, or the repository.

## Why macOS may prompt

macOS associates a Keychain item with the code identity that created it. A
prompt appears when a different identity reads the item. Development CLIs,
ad-hoc builds, or builds signed with a new certificate are different identities.

A clean install should create and read the item with the same signed sidecar, so
there should be no prompt during normal use. A single explicit prompt may still
appear on some systems; it asks for the **Mac login password**, not a Google or
OpenAI password.

## Release requirements

- Keep the same `Academia OS Beta Release Signing` certificate for every build.
- Sign the app and the sidecar with that certificate.
- Do not regenerate the certificate between releases.
- Keep the Google OAuth client secret in the release secret, not in Keychain.
- Rotate any OAuth secret that was exposed in a chat or commit.

## Clean-install test

Use a fresh macOS user account with no prior Academia Keychain items:

1. Install the DMG and move the app to `/Applications`.
2. Launch the app.
3. Connect Google.
4. Add one API provider key.
5. Quit and reopen the app.
6. Verify:
   - Google status is still connected.
   - The API provider still shows its models.
   - No repeated Keychain prompt appears.
7. Upgrade from the previous release and repeat steps 5–6.

If a prompt appears, confirm it is a one-time prompt. If it repeats, the build
is using a different code identity or two different executables are accessing
the same item.

## User-facing fallback

If macOS prompts, the app must explain:

> macOS is asking for your Mac login password to let Academia OS use its saved
> connection. This is not your Google, OpenAI, or other provider password.

Choosing **Deny** must not crash the app. The connection should show as locked
and offer a reconnect action.
