from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from academia_os.mcp_connections import MCPConnectionManager
from tests.test_mcp_remote import FakeRemoteServer, MemoryTokenStore
from tests.test_web import request, running_server

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_external_mcp.py"


def post(server: Any, path: str, value: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_mcp_connection_routes_manage_read_only_grants(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        server.mcp_manager = MCPConnectionManager(tmp_path / "runtime" / "mcp_connections.json")
        status, _, payload = request(server, "GET", "/api/v1/mcp/connections")
        assert status == 200
        assert json.loads(payload) == []

        status, _, payload = post(server, "/api/v1/mcp/connections", {
            "name": "Fake Research",
            "command": sys.executable,
            "args": [str(FAKE_SERVER)],
        })
        assert status == 200
        record = json.loads(payload)
        assert record["status"] == "unchecked"

        status, _, payload = post(server, "/api/v1/mcp/connections/inspect", {"id": record["id"]})
        assert status == 200
        assert json.loads(payload)["status"] == "available"

        status, _, payload = post(server, "/api/v1/mcp/connections/grant", {"id": record["id"], "tools": ["search_notes"]})
        assert status == 200
        assert json.loads(payload)["enabled"] is True

        status, _, payload = post(server, "/api/v1/mcp/connections/call", {"id": record["id"], "tool": "search_notes", "arguments": {"query": "research"}})
        assert status == 200
        assert json.loads(payload)["content"][0]["text"] == "ok"

        status, _, payload = post(server, "/api/v1/mcp/connections/grant", {"id": record["id"], "tools": ["write_note"]})
        assert status == 422
        assert json.loads(payload)["type"] == "MCPConnectionError"

        status, _, payload = post(server, "/api/v1/mcp/connections/disable", {"id": record["id"]})
        assert status == 200
        assert json.loads(payload)["enabled"] is False

        status, _, payload = post(server, "/api/v1/mcp/connections/disconnect", {"id": record["id"]})
        assert status == 200
        assert json.loads(payload)["id"] == record["id"]


def test_remote_mcp_oauth_routes_authorize_and_trust(tmp_path: Path) -> None:
    server = FakeRemoteServer()
    tokens = MemoryTokenStore()
    try:
        with running_server(tmp_path) as web:
            web.mcp_manager = MCPConnectionManager(
                tmp_path / "runtime" / "mcp_connections.json",
                token_store=tokens,  # type: ignore[arg-type]
            )
            status, _, payload = post(web, "/api/v1/mcp/connections/add-remote", {
                "name": "Remote Research",
                "url": server.origin + "/mcp",
            })
            assert status == 200
            record = json.loads(payload)
            assert record["scope"] == "read_only"
            assert record["trust"] == "remote_unverified"

            status, _, payload = post(web, "/api/v1/mcp/connections/authorize", {"id": record["id"]})
            assert status == 200
            started = json.loads(payload)
            assert started["auth_status"] == "pending"
            urllib.request.urlopen(started["authorization_url"], timeout=10).read()

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status, _, payload = post(web, "/api/v1/mcp/connections/oauth-status", {"id": record["id"]})
                assert status == 200
                auth = json.loads(payload)
                if auth["auth_status"] == "authorized":
                    break
                time.sleep(0.05)
            assert auth["auth_status"] == "authorized"
            assert record["id"] in tokens.values

            status, _, payload = post(web, "/api/v1/mcp/connections/inspect", {"id": record["id"]})
            assert status == 200
            assert json.loads(payload)["status"] == "available"

            status, _, payload = post(web, "/api/v1/mcp/connections/trust", {"id": record["id"]})
            assert status == 200
            assert json.loads(payload)["trust"] == "remote_trusted"

            status, _, payload = post(web, "/api/v1/mcp/connections/grant", {"id": record["id"], "tools": ["search_notes"]})
            assert status == 200
            assert json.loads(payload)["enabled"] is True

            status, _, payload = post(web, "/api/v1/mcp/connections/oauth-cancel", {"id": record["id"]})
            assert status == 422
            assert json.loads(payload)["type"] == "MCPConnectionError"

            status, _, payload = post(web, "/api/v1/mcp/connections/add-remote", {
                "name": "Pending Remote",
                "url": server.origin + "/mcp",
            })
            pending = json.loads(payload)
            status, _, payload = post(web, "/api/v1/mcp/connections/authorize", {"id": pending["id"]})
            assert status == 200
            status, _, payload = post(web, "/api/v1/mcp/connections/oauth-cancel", {"id": pending["id"]})
            assert status == 200
            assert json.loads(payload)["auth_status"] == "none"
    finally:
        server.close()
