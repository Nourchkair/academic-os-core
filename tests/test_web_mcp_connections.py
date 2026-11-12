from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from academia_os.mcp_connections import MCPConnectionManager
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
