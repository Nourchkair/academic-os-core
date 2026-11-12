from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from academia_os.mcp_connections import MCPConnectionError, MCPConnectionManager


class MemoryTokenStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def save(self, connection_id: str, tokens: dict[str, Any]) -> None:
        self.values[connection_id] = dict(tokens)

    def load(self, connection_id: str) -> dict[str, Any] | None:
        return self.values.get(connection_id)

    def delete(self, connection_id: str) -> None:
        self.values.pop(connection_id, None)


class FakeRemoteServer:
    def __init__(self, require_auth: bool = True) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.access_token = "access-test"
        self.require_auth = require_auth
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
                if parts.path == "/.well-known/oauth-protected-resource":
                    self._json(200, {"authorization_servers": [owner.origin], "scopes_supported": ["mcp.read"]})
                elif parts.path == "/.well-known/oauth-authorization-server":
                    self._json(200, {
                        "authorization_endpoint": owner.origin + "/authorize",
                        "token_endpoint": owner.origin + "/token",
                        "registration_endpoint": owner.origin + "/register",
                    })
                elif parts.path == "/authorize":
                    query = urllib.parse.parse_qs(parts.query)
                    state = query.get("state", [""])[0]
                    redirect = query.get("redirect_uri", [""])[0]
                    location = redirect + "?" + urllib.parse.urlencode({"code": "code-test", "state": state})
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                parts = urllib.parse.urlsplit(self.path)
                owner.requests.append((parts.path, self.headers.get("Authorization", ""), json.loads(body) if self.headers.get("Content-Type", "").startswith("application/json") and body else {}))
                if parts.path == "/register":
                    self._json(200, {"client_id": "client-test"})
                elif parts.path == "/token":
                    self._json(200, {"access_token": owner.access_token, "refresh_token": "refresh-test", "token_type": "Bearer", "expires_in": 3600})
                elif parts.path == "/mcp":
                    message = json.loads(body)
                    method = message.get("method")
                    if owner.require_auth and self.headers.get("Authorization") != f"Bearer {owner.access_token}":
                        self._json(401, {"error": "unauthorized"})
                        return
                    if method == "initialize":
                        self._json(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "Remote Research", "version": "1.0"}, "capabilities": {"tools": {}}}})
                    elif method == "notifications/initialized":
                        self.send_response(202)
                        self.end_headers()
                    elif method == "tools/list":
                        self._json(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": {"tools": [
                            {"name": "search_notes", "description": "Search remote notes.", "annotations": {"readOnlyHint": True}},
                            {"name": "write_note", "description": "Write remote notes.", "annotations": {"readOnlyHint": False}},
                        ]}})
                    elif method == "tools/call":
                        self._json(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": {"content": [{"type": "text", "text": "remote-ok"}]}})
                    else:
                        self._json(200, {"jsonrpc": "2.0", "id": message.get("id"), "result": {}})
                else:
                    self.send_response(404)
                    self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def test_remote_oauth_keychain_inspect_and_read_only_call(tmp_path: Path) -> None:
    server = FakeRemoteServer()
    tokens = MemoryTokenStore()
    connections = MCPConnectionManager(tmp_path / "runtime" / "mcp_connections.json", token_store=tokens)  # type: ignore[arg-type]
    try:
        record = connections.add_remote(name="Remote Research", url=server.origin + "/mcp")
        assert record["transport"] == "http"
        assert record["trust"] == "remote_unverified"
        assert record["auth_status"] == "none"

        started = connections.begin_authorize(record["id"])
        assert started["authorization_url"].startswith(server.origin + "/authorize")
        urllib.request.urlopen(started["authorization_url"], timeout=10).read()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = connections.oauth_status(record["id"])
            if status["auth_status"] == "authorized":
                break
            time.sleep(0.05)
        assert status["auth_status"] == "authorized"
        assert record["id"] in tokens.values

        inspected = connections.inspect(record["id"])
        assert inspected["status"] == "available"
        assert [tool["name"] for tool in inspected["tools"]] == ["search_notes", "write_note"]

        with pytest.raises(MCPConnectionError, match="trust"):
            connections.grant(record["id"], ["search_notes"])

        trusted = connections.trust_remote(record["id"])
        assert trusted["trust"] == "remote_trusted"

        with pytest.raises(MCPConnectionError, match="read-only"):
            connections.grant(record["id"], ["write_note"])
        granted = connections.grant(record["id"], ["search_notes"])
        assert granted["enabled"] is True
        called = connections.call_read_tool(record["id"], "search_notes", {"query": "research"})
        assert called["content"][0]["text"] == "remote-ok"

        disconnected = connections.disconnect(record["id"])
        assert disconnected["id"] == record["id"]
        assert record["id"] not in tokens.values
    finally:
        server.close()
