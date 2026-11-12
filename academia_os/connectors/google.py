"""Google OAuth connection and bounded read-only Gmail/Calendar access.

The OAuth client id and secret are app-level configuration. They are stored in
the operating system credential store through ``keyring`` alongside the OAuth
tokens; the connector state file contains only client id, scopes, status, and
the signed-in account email. No credential or token is written to the academic
workspace.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import queue
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
KEYCHAIN_SERVICE = "academia-os-google-oauth"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
OAUTH_TIMEOUT_SECONDS = 180.0
TOKEN_REFRESH_MARGIN_SECONDS = 60.0

DEFAULT_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

_STATUSES = {"not_configured", "configured", "pending", "authorized", "error"}


class GoogleConnectorError(ValueError):
    """A Google connector operation failed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000 or "\x00" in value:
        raise GoogleConnectorError("Google endpoint URL is invalid")
    parts = urllib.parse.urlsplit(value.strip())
    if parts.username or parts.password or parts.fragment:
        raise GoogleConnectorError("Google endpoint URL must not include credentials or a fragment")
    if parts.scheme == "https" and parts.hostname:
        return value.strip()
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip()
    raise GoogleConnectorError("Google endpoints must use HTTPS; HTTP is allowed only on loopback for tests")


def _http(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 25.0,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(_safe_url(url), data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise GoogleConnectorError("Google response exceeded the local size limit")
            return response.status, {key.lower(): value for key, value in response.headers.items()}, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, payload
    except (OSError, urllib.error.URLError) as exc:
        raise GoogleConnectorError(f"Google could not be reached: {exc}") from exc


def _json_request(method: str, url: str, *, body: Mapping[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, _headers, payload = _http(method, url, body=data, headers=headers)
    if status < 200 or status >= 300:
        raise GoogleConnectorError(f"Google returned HTTP {status}")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleConnectorError("Google returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise GoogleConnectorError("Google returned an unexpected JSON shape")
    return value


def _form_request(url: str, values: Mapping[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(values).encode("utf-8")
    status, _headers, payload = _http(
        "POST",
        url,
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    if status < 200 or status >= 300:
        raise GoogleConnectorError(f"Google token endpoint returned HTTP {status}")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleConnectorError("Google token endpoint returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise GoogleConnectorError("Google token endpoint returned an unexpected response")
    return value


class GoogleCredentialStore:
    """Keychain-backed client credentials and OAuth tokens."""

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise GoogleConnectorError("Google sign-in requires the keyring package") from exc
        return keyring

    def _save(self, account: str, value: Mapping[str, Any]) -> None:
        try:
            self._keyring().set_password(self.service, account, json.dumps(dict(value), separators=(",", ":")))
        except Exception as exc:
            raise GoogleConnectorError(f"Google credentials could not be saved to the system credential store: {exc}") from exc

    def _load(self, account: str) -> dict[str, Any] | None:
        try:
            raw = self._keyring().get_password(self.service, account)
        except Exception as exc:
            raise GoogleConnectorError(f"Google credentials could not be read from the system credential store: {exc}") from exc
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise GoogleConnectorError("stored Google credential data is invalid") from exc
        if not isinstance(value, dict):
            raise GoogleConnectorError("stored Google credential data is invalid")
        return value

    def save_client(self, client_id: str, client_secret: str) -> None:
        self._save("client", {"client_id": client_id, "client_secret": client_secret})

    def load_client(self) -> dict[str, str] | None:
        value = self._load("client")
        if value is None:
            return None
        client_id = value.get("client_id")
        client_secret = value.get("client_secret")
        if not isinstance(client_id, str) or not client_id or not isinstance(client_secret, str) or not client_secret:
            raise GoogleConnectorError("stored Google client credentials are incomplete")
        return {"client_id": client_id, "client_secret": client_secret}

    def save_tokens(self, tokens: Mapping[str, Any]) -> None:
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise GoogleConnectorError("Google token response did not include an access token")
        safe = {
            "access_token": access,
            "refresh_token": tokens.get("refresh_token") if isinstance(tokens.get("refresh_token"), str) else None,
            "token_type": tokens.get("token_type") if isinstance(tokens.get("token_type"), str) else "Bearer",
            "scope": tokens.get("scope") if isinstance(tokens.get("scope"), str) else None,
            "expires_at": tokens.get("expires_at") if isinstance(tokens.get("expires_at"), (int, float)) else None,
        }
        self._save("tokens", safe)

    def load_tokens(self) -> dict[str, Any] | None:
        value = self._load("tokens")
        if value is None:
            return None
        if not isinstance(value.get("access_token"), str) or not value["access_token"]:
            raise GoogleConnectorError("stored Google token data is invalid")
        return value

    def delete_tokens(self) -> None:
        try:
            self._keyring().delete_password(self.service, "tokens")
        except Exception:
            return

    def delete_all(self) -> None:
        self.delete_tokens()
        try:
            self._keyring().delete_password(self.service, "client")
        except Exception:
            return


def _token_bundle(value: Mapping[str, Any], fallback_refresh: str | None = None) -> dict[str, Any]:
    access = value.get("access_token")
    if not isinstance(access, str) or not access:
        raise GoogleConnectorError("Google token response did not include an access token")
    expires_in = value.get("expires_in")
    refresh = value.get("refresh_token") if isinstance(value.get("refresh_token"), str) else fallback_refresh
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": value.get("token_type") if isinstance(value.get("token_type"), str) else "Bearer",
        "scope": value.get("scope") if isinstance(value.get("scope"), str) else None,
        "expires_at": time.time() + expires_in if isinstance(expires_in, (int, float)) and expires_in > 0 else None,
    }


class _OAuthSession:
    def __init__(self, connector: "GoogleConnector", client: Mapping[str, str], scopes: list[str], timeout: float) -> None:
        self.connector = connector
        self.client = dict(client)
        self.scopes = scopes
        self.timeout = timeout
        self.state = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode("ascii").rstrip("=")
        self.verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
        self.redirect_uri = ""
        self.authorization_url = ""
        self.status = "pending"
        self.error: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._queue: queue.Queue[tuple[str | None, str | None]] = queue.Queue()
        self._cancelled = False

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parts.query)
                if query.get("state", [None])[0] != owner.state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Google OAuth state did not match. Return to Academia OS.")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Google sign-in complete</h1><p>You can close this window and return to Academia OS.</p></body></html>")
                owner._queue.put((query.get("code", [None])[0], query.get("error", [None])[0]))

        return Handler

    def start(self) -> str:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{port}"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        query = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client["client_id"],
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": self.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        })
        self.authorization_url = f"{AUTHORIZATION_ENDPOINT}{'&' if '?' in AUTHORIZATION_ENDPOINT else '?'}{query}"
        threading.Thread(target=self._serve, name="academia-google-oauth-callback", daemon=True).start()
        return self.authorization_url

    def _serve(self) -> None:
        assert self._server is not None
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()

    def wait_for_code(self) -> tuple[str, str]:
        code, error = self._queue.get(timeout=self.timeout)
        if error:
            raise GoogleConnectorError(f"Google authorization failed: {error}")
        if not code:
            raise GoogleConnectorError("Google callback did not include a code")
        return code, self.redirect_uri

    def cancel(self) -> None:
        self._cancelled = True
        self.status = "cancelled"
        self.close()

    def close(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None


class GoogleConnector:
    def __init__(self, state_path: Path, *, store: GoogleCredentialStore | None = None) -> None:
        self.state_path = Path(state_path)
        self.store = store or GoogleCredentialStore()
        self._lock = threading.RLock()
        self._session: _OAuthSession | None = None

    def _default_state(self) -> dict[str, Any]:
        now = _now()
        return {
            "schema_version": 1,
            "client_id": None,
            "scopes": list(DEFAULT_SCOPES),
            "auth_status": "not_configured",
            "account_email": None,
            "authorization_url": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "last_checked_at": None,
        }

    def _validate(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise GoogleConnectorError("Google connector state must be an object")
        state = self._default_state()
        state.update({key: value[key] for key in state if key in value})
        if state["auth_status"] not in _STATUSES:
            raise GoogleConnectorError("Google connector status is invalid")
        if state["client_id"] is not None and not isinstance(state["client_id"], str):
            raise GoogleConnectorError("Google client id is invalid")
        if not isinstance(state["scopes"], list) or any(not isinstance(item, str) for item in state["scopes"]):
            raise GoogleConnectorError("Google scopes are invalid")
        for key in ("account_email", "authorization_url", "error", "last_checked_at"):
            if state[key] is not None and not isinstance(state[key], str):
                raise GoogleConnectorError(f"Google {key} is invalid")
        return state

    def _read(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return self._default_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoogleConnectorError("Google connector state is not valid JSON") from exc
        return self._validate(value)

    def _write(self, state: Mapping[str, Any]) -> dict[str, Any]:
        state = self._validate({**state, "updated_at": _now()})
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)
        return state

    def _update(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            return self._write({**self._read(), **fields})

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._read()
        tokens = self.store.load_tokens()
        if state["auth_status"] == "authorized" and tokens is None:
            state = self._update(auth_status="error", error="Google tokens are missing; connect again.", account_email=None)
        return state

    def configure(self, *, client_id: str, client_secret: str) -> dict[str, Any]:
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 500:
            raise GoogleConnectorError("Google client id is required")
        if not isinstance(client_secret, str) or not client_secret.strip() or len(client_secret) > 500:
            raise GoogleConnectorError("Google client secret is required")
        self.store.save_client(client_id.strip(), client_secret.strip())
        self.store.delete_tokens()
        return self._update(
            client_id=client_id.strip(),
            auth_status="configured",
            account_email=None,
            authorization_url=None,
            error=None,
            last_checked_at=None,
        )

    def begin_authorize(self) -> dict[str, Any]:
        with self._lock:
            if self._session is not None and self._session.status == "pending":
                return {
                    "authorization_url": self._session.authorization_url,
                    "auth_status": "pending",
                    "redirect_uri": self._session.redirect_uri,
                    "expires_in": int(self._session.timeout),
                    "connection": self._read(),
                }
            client = self.store.load_client()
            if client is None:
                raise GoogleConnectorError("configure a Google OAuth client before connecting")
            state = self._read()
            session = _OAuthSession(self, client, list(state["scopes"]), OAUTH_TIMEOUT_SECONDS)
            url = session.start()
            self._session = session
            state = self._write({**state, "auth_status": "pending", "authorization_url": url, "error": None})
            threading.Thread(target=self._authorize_worker, args=(session,), name="academia-google-oauth-worker", daemon=True).start()
            return {
                "authorization_url": url,
                "auth_status": "pending",
                "redirect_uri": session.redirect_uri,
                "expires_in": int(session.timeout),
                "connection": state,
            }

    def _authorize_worker(self, session: _OAuthSession) -> None:
        try:
            code, redirect_uri = session.wait_for_code()
            client = session.client
            value = _form_request(TOKEN_ENDPOINT, {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "code_verifier": session.verifier,
            })
            bundle = _token_bundle(value)
            self.store.save_tokens(bundle)
            account = _json_request("GET", USERINFO_ENDPOINT, token=bundle["access_token"])
            email = account.get("email") if isinstance(account.get("email"), str) else None
            session.status = "authorized"
            self._update(
                auth_status="authorized",
                account_email=email,
                authorization_url=None,
                error=None,
                last_checked_at=_now(),
            )
        except (GoogleConnectorError, OSError, queue.Empty) as exc:
            if not session._cancelled:
                session.status = "error"
                session.error = "Google sign-in timed out" if isinstance(exc, queue.Empty) else str(exc)
                self._update(auth_status="error", error=session.error, authorization_url=None)
        finally:
            session.close()
            with self._lock:
                if self._session is session:
                    self._session = None

    def oauth_status(self) -> dict[str, Any]:
        state = self.status()
        return {
            "auth_status": state["auth_status"],
            "authorization_url": state["authorization_url"],
            "error": state["error"],
            "connection": state,
        }

    def cancel_authorize(self) -> dict[str, Any]:
        with self._lock:
            session = self._session
            self._session = None
        if session is not None:
            session.cancel()
        return self._update(auth_status="configured", authorization_url=None, error="Google sign-in was cancelled.")

    def authorize(self, *, open_browser: bool = True, timeout: float = OAUTH_TIMEOUT_SECONDS) -> dict[str, Any]:
        started = self.begin_authorize()
        if open_browser:
            try:
                webbrowser.open(started["authorization_url"])
            except Exception:
                pass
        deadline = time.monotonic() + timeout + 5.0
        while time.monotonic() < deadline:
            state = self.status()
            if state["auth_status"] in {"authorized", "error", "configured"}:
                return state
            time.sleep(0.25)
        self.cancel_authorize()
        return self._update(auth_status="error", error="Google sign-in timed out.")

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            session = self._session
            self._session = None
        if session is not None:
            session.cancel()
        self.store.delete_tokens()
        return self._update(
            auth_status="configured",
            account_email=None,
            authorization_url=None,
            error="Google account disconnected.",
        )

    def _access_token(self) -> str:
        tokens = self.store.load_tokens()
        if tokens is None:
            raise GoogleConnectorError("connect a Google account first")
        expires_at = tokens.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at > time.time() + TOKEN_REFRESH_MARGIN_SECONDS:
            return str(tokens["access_token"])
        refresh = tokens.get("refresh_token")
        client = self.store.load_client()
        if not isinstance(refresh, str) or not refresh or client is None:
            raise GoogleConnectorError("Google sign-in expired; connect again")
        value = _form_request(TOKEN_ENDPOINT, {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
        })
        bundle = _token_bundle(value, fallback_refresh=refresh)
        self.store.save_tokens(bundle)
        return bundle["access_token"]

    def _api_get(self, url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        target = url
        if params:
            target = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)}"
        return _json_request("GET", target, token=self._access_token())

    def gmail_list(self, *, query: str = "", max_results: int = 10) -> dict[str, Any]:
        if not isinstance(query, str) or len(query) > 200:
            raise GoogleConnectorError("Gmail query must be under 200 characters")
        if not isinstance(max_results, int) or not 1 <= max_results <= 20:
            raise GoogleConnectorError("Gmail result count must be between 1 and 20")
        listing = self._api_get(f"{GMAIL_API}/users/me/messages", {"q": query or None, "maxResults": max_results})
        raw = listing.get("messages") if isinstance(listing.get("messages"), list) else []
        messages: list[dict[str, Any]] = []
        for item in raw[:max_results]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            detail = self._api_get(
                f"{GMAIL_API}/users/me/messages/{urllib.parse.quote(item['id'], safe='')}",
                {"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            )
            headers = _headers(detail)
            messages.append({
                "id": item["id"],
                "thread_id": item.get("threadId") if isinstance(item.get("threadId"), str) else None,
                "subject": headers.get("subject"),
                "from": headers.get("from"),
                "date": headers.get("date"),
                "snippet": detail.get("snippet") if isinstance(detail.get("snippet"), str) else None,
            })
        return {"query": query, "count": len(messages), "messages": messages}

    def gmail_get(self, message_id: str) -> dict[str, Any]:
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", message_id):
            raise GoogleConnectorError("Gmail message id is invalid")
        detail = self._api_get(
            f"{GMAIL_API}/users/me/messages/{urllib.parse.quote(message_id, safe='')}",
            {"format": "full"},
        )
        headers = _headers(detail)
        body = _message_body(detail.get("payload"))
        return {
            "id": message_id,
            "thread_id": detail.get("threadId") if isinstance(detail.get("threadId"), str) else None,
            "subject": headers.get("subject"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "date": headers.get("date"),
            "snippet": detail.get("snippet") if isinstance(detail.get("snippet"), str) else None,
            "body": body[:40_000],
            "truncated": len(body) > 40_000,
        }

    def calendar_list(self, *, time_min: str | None = None, time_max: str | None = None, max_results: int = 20) -> dict[str, Any]:
        if not isinstance(max_results, int) or not 1 <= max_results <= 50:
            raise GoogleConnectorError("Calendar result count must be between 1 and 50")
        start = time_min or datetime.now(timezone.utc).isoformat()
        value = self._api_get(
            f"{CALENDAR_API}/calendars/primary/events",
            {
                "timeMin": start,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max_results,
            },
        )
        raw = value.get("items") if isinstance(value.get("items"), list) else []
        events: list[dict[str, Any]] = []
        for item in raw[:max_results]:
            if not isinstance(item, dict):
                continue
            events.append({
                "id": item.get("id"),
                "summary": item.get("summary"),
                "status": item.get("status"),
                "start": item.get("start"),
                "end": item.get("end"),
                "location": item.get("location"),
                "html_link": item.get("htmlLink"),
            })
        return {"time_min": start, "time_max": time_max, "count": len(events), "events": events}


def _headers(value: Mapping[str, Any]) -> dict[str, str]:
    payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    found: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = header.get("name")
        content = header.get("value")
        if isinstance(name, str) and isinstance(content, str):
            found[name.casefold()] = content
    return found


def _decode_body(data: str) -> str:
    if not isinstance(data, str) or not data:
        return ""
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _message_body(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    mime = payload.get("mimeType") if isinstance(payload.get("mimeType"), str) else ""
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    if mime == "text/plain" and isinstance(body.get("data"), str):
        return html.unescape(_decode_body(body["data"])).strip()
    for part in parts:
        text = _message_body(part)
        if text:
            return text
    if mime == "text/html" and isinstance(body.get("data"), str):
        raw = _decode_body(body["data"])
        return re.sub(r"<[^>]+>", " ", html.unescape(raw)).strip()
    return ""
