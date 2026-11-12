# Google Gmail and Calendar connector

Academia OS can connect one Google account for read-only Gmail and Google
Calendar access. The connector is local: it opens Google's OAuth consent page in
the browser, receives the authorization code on a loopback callback, and stores
the OAuth client secret and tokens in the macOS Keychain. The academic workspace
is never used for credentials.

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
   - `https://www.googleapis.com/auth/calendar.events` (reserved for
     Review-gated calendar writes; not used yet)
5. Add each tester under **Audience → Test users**. Testing is limited to 100
   users, and external testing refresh tokens expire after 7 days.
6. Create an OAuth client of type **Desktop app** and download its JSON.

## Local setup

Import the downloaded JSON once:

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

## Dashboard

Settings includes a **Google account** card. It shows whether the app is
configured, connects or cancels the Google sign-in, shows the connected account
email, and disconnects the account. In the desktop app, choose the downloaded
Google client JSON once; in the browser dashboard, import the same JSON through
the file picker.

## Limits

- Gmail and Calendar reads are bounded and read-only.
- Study chat does not call the Google tools yet.
- Calendar create/edit is not implemented. It must go through Review with
  duplicate detection and post-write verification.
- Academia never sends school-account messages, submits coursework, or requests
  Google passwords.
- The OAuth client secret is not confidential for installed desktop apps, but it
  must still stay out of the repository, `profile.json`, workflow preferences,
  and the academic workspace.
