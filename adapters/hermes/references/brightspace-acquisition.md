# Hermes/Chromium optional acquisition adapter reference

This file is adapter-specific. Academia OS core does not require Hermes or Chromium.

## Safe retrieval sequence

For a user-approved request such as `Fetch Brightspace — [course] — Week [N]`:

1. Resolve the exact course folder and read its `README.md`, `USER_OVERRIDES.md`, `Course_Context.md`, and `Course_Status.md`.
2. Run the optional Hermes adapter's visible-browser preflight. The adapter may use `academic_os_brightspace_browser.py ensure` when installed. Confirm it identifies the user's real visible Chromium-family profile and never continue with a clean automation-only profile.
3. Snapshot the chosen Downloads directory before opening the school site. Use a timestamped manifest outside the academic root.
4. Navigate to the user's authenticated school session and verify institution, course code/title, semester, and requested week/module before downloading.
5. If redirected to sign-in, stop at the authentication boundary. The user authenticates manually. Never enter, request, store, or record credentials or MFA codes.
6. Compare Downloads against the pre-retrieval manifest. Only newly created or changed relevant academic files may be handed off.
7. Use the optional adapter handoff utility when available. It must SHA-256 check identity, skip identical files, preserve changed versions with collision-safe names, and place accepted files only in the exact course `00_INBOX/`.
8. Leave unsupported, ambiguous, or pre-existing Downloads content untouched. The Academia OS processing lifecycle performs classification and downstream propagation.

## Verification expectations

A successful retrieval requires evidence of authenticated session, exact course/week match, source URL or module identity, files newly created/changed by the request, handoff result, and unchanged duplicate behavior. Verify rendered page content rather than relying on navigation or a generic URL. Preserve stable course/module/topic IDs and direct topic URLs in provenance records when available. A login screen is not evidence of course access or download success. If no file was retrieved, say so explicitly and verify that the target inbox was not modified.

## Safety boundary

School-site acquisition is read-only. Do not submit work, answer quizzes, post, change settings, mark content complete intentionally, delete content, unenroll, or alter account settings. Preserve original files and log only operational metadata; logs and generated summaries are not academic sources.
