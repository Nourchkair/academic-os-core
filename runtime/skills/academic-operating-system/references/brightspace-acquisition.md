# Brightspace Acquisition Reference

## Safe retrieval sequence

For a request such as `Fetch Brightspace — [course] — Week [N]`:

1. Resolve the exact course folder and read its `README.md`, `USER_OVERRIDES.md`, `Course_Context.md`, and `Course_Status.md`.
2. Run `python3 ~/.hermes/scripts/academic_os_brightspace_browser.py ensure`. Confirm the JSON says `real_profile_ready`, `real_profile: true`, `clean_hermes_profile: false`, and identifies the pinned supported Chromium-family browser/profile. Never continue with a clean Hermes browser. If the verifier cannot attach to the pinned real profile, stop and report the failure.
3. Snapshot `~/Downloads` before opening Brightspace. Use a timestamped manifest outside the academic root.
4. Navigate to the authenticated the configured institution Brightspace session and verify institution, course code/title, semester, and requested week/module before downloading.
5. If redirected to the institution sign-in sign-in, stop at the authentication boundary. Never enter, request, store, or record credentials or MFA codes. Leave the visible local browser at the login screen for the user. After the user reports authentication complete, rerun the real-profile preflight and verify the same profile before resuming.
6. After retrieval, compare Downloads against the pre-retrieval manifest. Only newly created or changed relevant academic files may be handed off.
7. Use the deterministic handoff utility when available:
   `python3 ~/.hermes/scripts/academic_os_brightspace_handoff.py snapshot`
   then
   `python3 ~/.hermes/scripts/academic_os_brightspace_handoff.py handoff --before <manifest> --course-dir <course> --request '<request>'`
8. The utility uses SHA-256 identity checks, skips identical files, preserves changed versions with collision-safe names, and places accepted files only in the exact course `00_INBOX/`. It does not classify or sort them.
9. Leave unsupported, ambiguous, or pre-existing Downloads content untouched. The existing Inbox Processor performs classification and downstream propagation.

## Verification expectations

A successful retrieval requires evidence of: authenticated session, exact course/week match, source URL or module identity, files newly created/changed by the request, handoff result, and unchanged duplicate behavior. Verify the rendered page content for the exact course code/title and requested module/topic; do not rely on a successful HTTP navigation or a generic Brightspace URL. Record both the browser-facing profile label and actual profile directory when reporting preflight results, since labels such as `Work` can legitimately use a `Default` directory. Preserve stable course/module/topic IDs and the direct topic URL in provenance records when available. A browser login screen is not evidence of course access or download success. If no file was retrieved, say so explicitly and verify that the target inbox was not modified.

## Safety boundary

Brightspace is read-only acquisition. Do not submit work, answer quizzes, post, change settings, mark content complete intentionally, delete content, unenroll, or alter account settings. Preserve original files and log only operational metadata; the log and generated summaries are not academic sources.
