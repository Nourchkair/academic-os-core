# Google Gmail and Calendar connector

Academia OS can connect one Google account for bounded Gmail and Google Calendar
access. Gmail remains read-only; Calendar create/edit is gated through a
duplicate-checked Review proposal, explicit approval, separate execution, and
read-back verification. The connector is local: it opens Google's OAuth consent
page in the browser, receives the authorization code on a loopback callback, and
stores the OAuth client secret and tokens in the macOS Keychain. The academic
workspace is never used for credentials.

## Google Cloud setup (testing)

1. Create a Google Cloud project.
2. Enable the Gmail API and Google Calendar API.
3. Configure the OAuth consent screen as External, with publishing status
   **Testing**. Do not publish the app while testing.
4. Add the scopes:
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/calendar.events` (used only for
     Review-gated event create/edit)
5. Add each tester under **Audience → Test users**. Testing is limited to 100
   users, and external testing refresh tokens expire after 7 days.
6. Create an OAuth client of type **Desktop app** and download its JSON.

## OAuth client packaging

The official macOS release does not ask each tester to import a client file.
The release workflow embeds the app-level Desktop OAuth client JSON inside the
PyInstaller CLI sidecar. On first Google connection, the client id and secret
are copied to Keychain, and the embedded copy is only a bootstrap source.
Installed-app OAuth client secrets are not confidential, but the build secret
still must not be committed to the repository.

Before publishing a release, rotate any client secret that was pasted into a
chat or commit. Then configure a GitHub repository secret named
`ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64` with the base64-encoded Google Desktop
client JSON. For example, on macOS, use a local file and pipe it directly to
GitHub CLI (do not print the value):

```bash
base64 < ~/Downloads/client_secret_desktop.json | tr -d '\n' \
  | gh secret set ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64 --repo OWNER/REPOSITORY
```

The release workflow requires the secret and fails closed if it is missing.
Local sidecar builds use the Google client in the macOS Keychain by default;
developers can instead set `ACADEMIA_GOOGLE_CLIENT_JSON` to a local JSON path.
The temporary build staging file is mode `0600` and is removed with the build
directory. Do not upload it as a separate artifact.

## Local development setup

For an unpackaged development install, import the downloaded JSON once:

```bash
academia connectors google setup --client-json ~/Downloads/client_secret_*.json --json
```

The command stores the client id and secret in the system credential store and
writes only the client id, scopes, status, and account email to
`<runtime>/google_connector.json`.

Connect the account:

```bash
academia connectors google authorize --json
```

The browser opens Google's consent page. After approval, the tokens are stored
in Keychain.

Check the connection:

```bash
academia connectors google status --json
academia connectors google gmail list --max 5 --json
academia connectors google calendar list --max 10 --json
```

Disconnect and remove the tokens:

```bash
academia connectors google disconnect --json
```

## Dashboard and Study chat

Settings includes a **Google account** card. It shows whether the app is
configured, connects or cancels Google sign-in, shows the connected account
email, lists upcoming primary-calendar events, and provides forms to prepare
create/edit proposals. Official packaged builds bootstrap the OAuth client
automatically. An unpackaged desktop development build may import the JSON
once; a browser dashboard can also import it through its file picker.

Study chat has separate, opt-in Gmail and Calendar context toggles for each
message. Proposal mode has a further **Google Calendar proposals** grant. The
assistant can then prepare a create/edit proposal only when the student asks;
the proposal is duplicate-checked and opened in Review. Approval is followed by
a separate execute action. Execution checks duplicates and the reviewed event
version again, applies the change, reads the event back, and records verified
Activity. The model cannot approve or execute its own proposal.

For CLI use, create a Review proposal without changing Google:

```bash
academia connectors google calendar propose-create \
  --summary "Study block" \
  --start "2027-02-10T14:00:00-05:00" \
  --end "2027-02-10T15:00:00-05:00" --json
```

For an edit, use the exact event id from a Calendar read:

```bash
academia connectors google calendar propose-update EVENT_ID \
  --summary "Revised study block" \
  --start "2027-02-10T15:00:00-05:00" \
  --end "2027-02-10T16:00:00-05:00" --json
```

Review the generated item in the dashboard. After the explicit approval, execute
the separate action and verify the returned state:

```bash
academia review decide REVIEW_ID approve_action --json
academia review execute REVIEW_ID --json
```

## Limits

- Gmail and Calendar reads are bounded and read-only.
- Study chat can include bounded Gmail/Calendar context only when the student enables the Gmail or Calendar grant for that message.
- Calendar create/edit is limited to the connected primary calendar and timed
  events. Every change must be proposed in Review, explicitly approved, then
  separately executed. Duplicate checks run before proposal and execution;
  updates use the reviewed Google event ETag; execution reads back and verifies
  the exact effect. A changed/stale event fails rather than being overwritten.
- Portal access is not implemented. Academia does not automate Brightspace,
  Canvas, Moodle, or other school portals.
- Academia never sends school-account messages, submits coursework, or requests
  Google passwords.
- The OAuth client secret is not confidential for installed desktop apps, but it
  must still stay out of the repository, `profile.json`, workflow preferences,
  and the academic workspace.
