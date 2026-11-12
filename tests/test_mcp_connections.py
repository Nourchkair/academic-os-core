from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from academia_os.mcp_connections import MCPConnectionError, MCPConnectionManager

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_external_mcp.py"


def manager(tmp_path: Path) -> MCPConnectionManager:
    return MCPConnectionManager(tmp_path / "runtime" / "mcp_connections.json")


def add_fake(manager: MCPConnectionManager) -> dict:
    return manager.add(
        name="Fake Research",
        command=sys.executable,
        args=[str(FAKE_SERVER)],
    )


def test_add_inspect_and_grant_only_read_only_tools(tmp_path: Path) -> None:
    connections = manager(tmp_path)
    record = add_fake(connections)
    assert record["enabled"] is False
    assert record["scope"] == "read_only"
    assert record["status"] == "unchecked"
    assert record["tools"] == []

    inspected = connections.inspect(record["id"])
    assert inspected["status"] == "available"
    assert inspected["server_info"] == {"name": "Fake Research", "version": "1.0"}
    assert [tool["name"] for tool in inspected["tools"]] == ["read_note", "search_notes", "write_note"]
    assert inspected["tools"][0]["read_only"] is True
    assert inspected["tools"][-1]["read_only"] is False
    assert inspected["enabled"] is False

    granted = connections.grant(record["id"], ["search_notes", "read_note"])
    assert granted["granted_tools"] == ["search_notes", "read_note"]
    assert granted["enabled"] is True

    with pytest.raises(MCPConnectionError, match="read-only"):
        connections.grant(record["id"], ["write_note"])

    called = connections.call_read_tool(record["id"], "search_notes", {"query": "research"})
    assert called["tool"] == "search_notes"
    assert called["is_error"] is False
    assert called["content"][0]["text"] == "ok"
    with pytest.raises(MCPConnectionError, match="not granted"):
        connections.call_read_tool(record["id"], "write_note", {})

    disabled = connections.disable(record["id"])
    assert disabled["enabled"] is False
    enabled = connections.enable(record["id"])
    assert enabled["enabled"] is True
    disconnected = connections.disconnect(record["id"])
    assert disconnected["id"] == record["id"]
    assert connections.list() == []


def test_connection_state_persists_and_duplicate_names_fail(tmp_path: Path) -> None:
    first = manager(tmp_path)
    record = add_fake(first)
    first.inspect(record["id"])
    first.grant(record["id"], ["search_notes"])
    again = manager(tmp_path)
    saved = again.list()[0]
    assert saved["id"] == record["id"]
    assert saved["granted_tools"] == ["search_notes"]
    assert saved["status"] == "available"
    with pytest.raises(MCPConnectionError, match="already exists"):
        add_fake(again)


def test_unavailable_server_and_corrupt_state_fail_closed(tmp_path: Path) -> None:
    connections = manager(tmp_path)
    record = connections.add(name="Missing", command=str(tmp_path / "not-a-server"))
    inspected = connections.inspect(record["id"])
    assert inspected["status"] == "error"
    assert inspected["tools"] == []
    with pytest.raises(MCPConnectionError, match="inspect"):
        connections.enable(record["id"])

    path = tmp_path / "runtime" / "mcp_connections.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(Exception, match="not valid JSON"):
        connections.list()


def test_cli_remote_add_trust_and_inspect(tmp_path: Path) -> None:
    import json

    from tests.test_agent_interface import prepared_workspace, run_cli
    from tests.test_mcp_remote import FakeRemoteServer

    remote = FakeRemoteServer(require_auth=False)
    try:
        _, _, profile = prepared_workspace(tmp_path / "workspace")
        added = run_cli(profile, "mcp-connections", "add-remote", "--name", "Remote Research", "--url", remote.origin + "/mcp", "--json")
        assert added.returncode == 0, added.stderr
        record = json.loads(added.stdout)
        assert record["transport"] == "http"
        assert record["trust"] == "remote_unverified"
        assert record["url"] == remote.origin + "/mcp"

        insecure = run_cli(profile, "mcp-connections", "add-remote", "--name", "Insecure", "--url", "http://example.test/mcp", "--json")
        assert insecure.returncode != 0
        assert "HTTPS" in insecure.stdout + insecure.stderr

        early_trust = run_cli(profile, "mcp-connections", "trust", record["id"], "--json")
        assert early_trust.returncode != 0
        assert "inspect" in early_trust.stdout + early_trust.stderr

        inspected = run_cli(profile, "mcp-connections", "inspect", record["id"], "--json")
        assert inspected.returncode == 0, inspected.stderr
        assert json.loads(inspected.stdout)["status"] == "available"

        trusted = run_cli(profile, "mcp-connections", "trust", record["id"], "--json")
        assert trusted.returncode == 0, trusted.stderr
        assert json.loads(trusted.stdout)["trust"] == "remote_trusted"
    finally:
        remote.close()


def test_cli_mcp_connections_lifecycle(tmp_path: Path) -> None:
    import json

    from tests.test_agent_interface import prepared_workspace, run_cli

    _, _, profile = prepared_workspace(tmp_path / "workspace")
    added = run_cli(profile, "mcp-connections", "add", "--name", "Fake Research", "--command", sys.executable, "--arg", str(FAKE_SERVER), "--json")
    assert added.returncode == 0, added.stderr
    record = json.loads(added.stdout)
    assert record["status"] == "unchecked"

    inspected = run_cli(profile, "mcp-connections", "inspect", record["id"], "--json")
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["status"] == "available"

    granted = run_cli(profile, "mcp-connections", "grant", record["id"], "--tool", "search_notes", "--json")
    assert granted.returncode == 0, granted.stderr
    assert json.loads(granted.stdout)["enabled"] is True

    listed = run_cli(profile, "mcp-connections", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)[0]["granted_tools"] == ["search_notes"]

    called = run_cli(profile, "mcp-connections", "call", record["id"], "--tool", "search_notes", "--arguments", '{"query":"research"}', "--json")
    assert called.returncode == 0, called.stderr
    assert json.loads(called.stdout)["content"][0]["text"] == "ok"

    disabled = run_cli(profile, "mcp-connections", "disable", record["id"], "--json")
    assert disabled.returncode == 0, disabled.stderr
    assert json.loads(disabled.stdout)["enabled"] is False

    disconnected = run_cli(profile, "mcp-connections", "disconnect", record["id"], "--json")
    assert disconnected.returncode == 0, disconnected.stderr
    assert json.loads(run_cli(profile, "mcp-connections", "list", "--json").stdout) == []
