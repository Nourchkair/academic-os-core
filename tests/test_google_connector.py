from __future__ import annotations

import json
import threading
from datetime import datetime
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from academia_os.connectors import google


class MemoryGoogleStore:
    def __init__(self) -> None:
        self.client: dict[str, str] | None = None
        self.tokens: dict[str, Any] | None = None

    def save_client(self, client_id: str, client_secret: str) -> None:
        self.client = {"client_id": client_id, "client_secret": client_secret}

    def load_client(self) -> dict[str, str] | None:
        return dict(self.client) if self.client else None

    def save_tokens(self, tokens: dict[str, Any]) -> None:
        self.tokens = dict(tokens)

    def load_tokens(self) -> dict[str, Any] | None:
        return dict(self.tokens) if self.tokens else None

    def delete_tokens(self) -> None:
        self.tokens = None


class FakeGoogleServer:
    def __init__(self) -> None:
        self.access_token = "google-access"
        self.refresh_token = "google-refresh"
        self.requests: list[str] = []
        self.calendar_events: dict[str, dict[str, Any]] = {
            "event-1": {
                "id": "event-1",
                "etag": '"etag-1"',
                "summary": "Study session",
                "status": "confirmed",
                "start": {"dateTime": "2030-02-10T10:00:00-05:00"},
                "end": {"dateTime": "2030-02-10T11:00:00-05:00"},
                "location": "Room 203",
                "htmlLink": "https://calendar.example.test/event-1",
            }
        }
        self.calendar_counter = 1
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _json(self, status: int, value: dict[str, Any]) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                owner.requests.append(parts.path)
                if parts.path == "/authorize":
                    query = urllib.parse.parse_qs(parts.query)
                    redirect = query.get("redirect_uri", [""])[0]
                    state = query.get("state", [""])[0]
                    location = redirect + "?" + urllib.parse.urlencode({"code": "google-code", "state": state})
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != f"Bearer {owner.access_token}":
                    self._json(401, {"error": "unauthorized"})
                    return
                if parts.path == "/userinfo":
                    self._json(200, {"email": "student@example.edu", "name": "Student"})
                elif parts.path == "/gmail/v1/users/me/messages":
                    self._json(200, {"messages": [{"id": "m1", "threadId": "t1"}]})
                elif parts.path == "/gmail/v1/users/me/messages/m1":
                    self._json(200, {
                        "id": "m1",
                        "threadId": "t1",
                        "snippet": "First message",
                        "payload": {
                            "mimeType": "text/plain",
                            "headers": [
                                {"name": "Subject", "value": "Welcome"},
                                {"name": "From", "value": "advisor@example.edu"},
                                {"name": "Date", "value": "Mon, 10 Nov 2026 10:00:00 -0500"},
                            ],
                            "body": {"data": "SGVsbG8gZnJvbSBHbWFpbA"},
                        },
                    })
                elif parts.path == "/calendar/v3/calendars/primary/events":
                    query = urllib.parse.parse_qs(parts.query)
                    time_min = query.get("timeMin", [None])[0]
                    time_max = query.get("timeMax", [None])[0]
                    search = query.get("q", [None])[0]
                    items = list(owner.calendar_events.values())
                    if search:
                        items = [item for item in items if search.casefold() in str(item.get("summary", "")).casefold()]
                    def parsed(value: Any) -> datetime | None:
                        if not isinstance(value, str):
                            return None
                        try:
                            return datetime.fromisoformat(value.replace("Z", "+00:00"))
                        except ValueError:
                            return None
                    lower = parsed(time_min)
                    upper = parsed(time_max)
                    if lower is not None:
                        items = [item for item in items if (parsed(item.get("end", {}).get("dateTime")) or lower) >= lower]
                    if upper is not None:
                        items = [item for item in items if (parsed(item.get("start", {}).get("dateTime")) or upper) <= upper]
                    self._json(200, {"items": items})
                elif parts.path.startswith("/calendar/v3/calendars/primary/events/"):
                    event_id = parts.path.rsplit("/", 1)[-1]
                    event = owner.calendar_events.get(event_id)
                    self._json(200 if event else 404, event or {"error": "not found"})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                owner.requests.append(parts.path)
                if parts.path in {"/token", "/token-refresh"}:
                    self._json(200, {
                        "access_token": owner.access_token,
                        "refresh_token": owner.refresh_token,
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    })
                elif parts.path == "/calendar/v3/calendars/primary/events":
                    event = json.loads(body)
                    if event.get("id") in owner.calendar_events:
                        self._json(409, {"error": "duplicate id"})
                        return
                    owner.calendar_counter += 1
                    event["etag"] = f'"etag-{owner.calendar_counter}"'
                    event["status"] = "confirmed"
                    owner.calendar_events[event["id"]] = event
                    self._json(200, event)
                else:
                    self._json(404, {"error": "not found"})

            def do_PATCH(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                event_id = parts.path.rsplit("/", 1)[-1]
                event = owner.calendar_events.get(event_id)
                if event is None:
                    self._json(404, {"error": "not found"})
                    return
                if self.headers.get("If-Match") != event.get("etag"):
                    self._json(412, {"error": "etag mismatch"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                patch = json.loads(self.rfile.read(length).decode("utf-8"))
                for key, value in patch.items():
                    if key in {"start", "end"} and isinstance(value, dict):
                        event[key] = {**event.get(key, {}), **value}
                    elif key in {"location", "description"} and value == "":
                        event.pop(key, None)
                    else:
                        event[key] = value
                owner.calendar_counter += 1
                event["etag"] = f'"etag-{owner.calendar_counter}"'
                self._json(200, event)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def _configure(connector: google.GoogleConnector, server: FakeGoogleServer) -> None:
    google.AUTHORIZATION_ENDPOINT = server.origin + "/authorize"
    google.TOKEN_ENDPOINT = server.origin + "/token"
    google.USERINFO_ENDPOINT = server.origin + "/userinfo"
    google.GMAIL_API = server.origin + "/gmail/v1"
    google.CALENDAR_API = server.origin + "/calendar/v3"
    connector.configure(client_id="client-id", client_secret="client-secret")


def _wait_authorized(connector: google.GoogleConnector) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = connector.status()
        if status["auth_status"] in {"authorized", "error"}:
            return status
        time.sleep(0.05)
    raise AssertionError("Google authorization did not complete")


def test_google_oauth_gmail_and_calendar_reads(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    store = MemoryGoogleStore()
    connector = google.GoogleConnector(tmp_path / "google_connector.json", store=store)  # type: ignore[arg-type]
    try:
        _configure(connector, server)
        started = connector.begin_authorize()
        assert started["auth_status"] == "pending"
        assert started["authorization_url"].startswith(server.origin + "/authorize")
        urllib.request.urlopen(started["authorization_url"], timeout=10).read()

        status = _wait_authorized(connector)
        assert status["auth_status"] == "authorized"
        assert status["account_email"] == "student@example.edu"
        assert store.tokens is not None

        listing = connector.gmail_list(query="from:advisor", max_results=2)
        assert listing["count"] == 1
        assert listing["messages"][0]["subject"] == "Welcome"
        message = connector.gmail_get("m1")
        assert message["body"] == "Hello from Gmail"

        events = connector.calendar_list(max_results=5)
        assert events["count"] == 1
        assert events["events"][0]["summary"] == "Study session"

        disconnected = connector.disconnect()
        assert disconnected["auth_status"] == "configured"
        assert store.tokens is None
        assert connector.status()["account_email"] is None
    finally:
        server.close()


def test_google_refresh_tokens_and_errors(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    store = MemoryGoogleStore()
    connector = google.GoogleConnector(tmp_path / "google_connector.json", store=store)  # type: ignore[arg-type]
    try:
        _configure(connector, server)
        started = connector.begin_authorize()
        urllib.request.urlopen(started["authorization_url"], timeout=10).read()
        _wait_authorized(connector)
        assert store.tokens is not None
        store.tokens["expires_at"] = time.time() - 1
        store.tokens["access_token"] = "expired"
        google.TOKEN_ENDPOINT = server.origin + "/token-refresh"
        listing = connector.gmail_list(max_results=1)
        assert listing["count"] == 1
        assert store.tokens["access_token"] == "google-access"

        connector.cancel_authorize()
        assert connector.status()["auth_status"] == "configured"
    finally:
        server.close()


def test_google_calendar_event_create_update_and_duplicate_detection(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    store = MemoryGoogleStore()
    connector = google.GoogleConnector(tmp_path / "google_connector.json", store=store)  # type: ignore[arg-type]
    try:
        _configure(connector, server)
        store.tokens = {
            "access_token": server.access_token,
            "refresh_token": server.refresh_token,
            "expires_at": time.time() + 3600,
        }
        event = {
            "summary": "POL 2103 study block",
            "start": "2027-02-10T14:00:00Z",
            "end": "2027-02-10T15:00:00Z",
            "location": "Library",
            "description": "Review lecture notes",
        }
        assert connector.calendar_find_duplicates(event) == []
        created = connector.calendar_create(event, event_id="abcdef123456")
        assert created["id"] == "abcdef123456"
        assert created["location"] == "Library"
        assert connector.calendar_get("abcdef123456")["summary"] == "POL 2103 study block"
        assert len(connector.calendar_find_duplicates(event)) == 1

        current = connector.calendar_get("event-1")
        updated = connector.calendar_patch(
            "event-1",
            {"summary": "Updated study session"},
            etag=current["etag"],
        )
        assert updated["summary"] == "Updated study session"
        assert connector.calendar_get("event-1")["etag"] != current["etag"]

        with pytest.raises(google.GoogleConnectorError, match="HTTP 412"):
            connector.calendar_patch("event-1", {"summary": "Stale update"}, etag=current["etag"])
    finally:
        server.close()
