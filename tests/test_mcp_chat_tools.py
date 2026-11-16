from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from academia_os import mcp_server
from academia_os.assistant.contracts import AssistantError, Scope, ScopeKind, ToolGrant
from academia_os.assistant.registry import descriptors, invoke_granted
from academia_os.assistant.runtime import tools_for_scope
from academia_os.assistant.tools.read import ReadContext
from academia_os.config import load_config, runtime_directory
from academia_os.mcp_connections import MCPConnectionManager
from tests.test_agent_interface import prepared_workspace

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_external_mcp.py"


def connection(tmp_path: Path):
    _, _, profile = prepared_workspace(tmp_path)
    config = load_config(profile)
    manager = MCPConnectionManager(runtime_directory(config) / "mcp_connections.json")
    record = manager.add(name="Fake Research", command=sys.executable, args=[str(FAKE_SERVER)])
    manager.inspect(record["id"])
    return profile, config, manager, record


def test_mcp_call_tool_runs_a_granted_action_and_logs_activity(tmp_path: Path) -> None:
    _, config, _manager, record = connection(tmp_path)
    context = replace(ReadContext.create(config), mcp_grants={record["id"]: frozenset({"write_note"})})

    result = invoke_granted(
        "mcp.call",
        {"connection_id": record["id"], "tool": "write_note", "arguments": {"id": "note-1"}},
        context,
        grants=ToolGrant(frozenset({"mcp.call"})),
    )

    assert result.data["tool"] == "write_note"
    assert result.data["is_error"] is False
    activity = (Path(config["academic"]["root_directory"]) / ".academia" / "activity.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in activity.splitlines() if line.strip()]
    assert any(event["event_type"] == "mcp.tool_called" for event in events)


def test_mcp_call_tool_rejects_an_ungranted_tool(tmp_path: Path) -> None:
    _, config, _manager, record = connection(tmp_path)
    context = replace(ReadContext.create(config), mcp_grants={record["id"]: frozenset({"read_note"})})

    with pytest.raises(AssistantError, match="not granted"):
        invoke_granted(
            "mcp.call",
            {"connection_id": record["id"], "tool": "write_note", "arguments": {}},
            context,
            grants=ToolGrant(frozenset({"mcp.call"})),
        )


def test_mcp_call_is_hidden_unless_granted() -> None:
    assert "mcp.call" not in {tool["name"] for tool in descriptors()}
    scope = Scope(kind=ScopeKind.SEMESTER, semester="Fall 2026")

    without = {tool["name"] for tool in tools_for_scope(scope, ToolGrant.none())}
    with_grant = {tool["name"] for tool in tools_for_scope(scope, ToolGrant(frozenset({"mcp.call"})))}

    assert "mcp.call" not in without
    assert "mcp.call" in with_grant


def test_chat_instruction_exposes_tool_docs_and_schemas(tmp_path: Path) -> None:
    from academia_os.dashboard_chat import _mcp_instruction

    profile, _config, _manager, record = connection(tmp_path)

    text = _mcp_instruction([{"connection_id": record["id"], "tools": ["search_notes"]}], profile)

    assert "never ask the student" in text
    assert "historical context" in text
    assert "search_notes" in text
    assert "arguments schema" in text
    assert "DOWNLOAD INTO ACADEMIA" in text
    assert "academia_import_download" in text
    assert "write_note" not in text


def test_mcp_server_proxy_lists_and_calls_only_granted_tools(tmp_path: Path) -> None:
    profile, _config, _manager, record = connection(tmp_path)
    grants = {record["id"]: {"write_note"}}

    tools = {tool["name"] for tool in mcp_server._tools_for_mode(False, False, None, grants)}
    assert "academia_mcp_call" in tools

    result = mcp_server._call_tool(
        "academia_mcp_call",
        {"connection_id": record["id"], "tool": "write_note", "arguments": {"id": "note-1"}},
        profile,
        mcp_grants=grants,
    )
    assert result["tool"] == "write_note"

    with pytest.raises(mcp_server.McpError, match="not granted"):
        mcp_server._call_tool(
            "academia_mcp_call",
            {"connection_id": record["id"], "tool": "read_note", "arguments": {}},
            profile,
            mcp_grants=grants,
        )


def test_download_intake_tools_require_the_explicit_runtime_flag(tmp_path: Path) -> None:
    profile, config, _manager, _record = connection(tmp_path)

    default = {tool["name"] for tool in mcp_server._tools_for_mode(True, False, None, None)}
    enabled = {tool["name"] for tool in mcp_server._tools_for_mode(True, False, None, None, True)}

    assert "academia_import_download" not in default
    assert "academia_download_intake" not in default
    assert {"academia_download_intake", "academia_import_download"} <= enabled

    info = mcp_server._call_tool("academia_download_intake", {}, profile, read_only=True, download_intake=True)
    assert Path(info["staging_directory"]).is_dir()
    assert info["max_file_bytes"] > 0


def test_import_download_copies_from_staging_and_removes_staged_copy(tmp_path: Path) -> None:
    profile, config, _manager, _record = connection(tmp_path)
    staging = runtime_directory(config) / "download_intake"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / "lecture-6.png"
    staged.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

    result = mcp_server._call_tool(
        "academia_import_download",
        {
            "staged_path": str(staged),
            "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX",
            "source_url": "https://brightspace.example/course/lecture-6?token=secret#fragment",
            "file_name": "Lecture 6 - Rousseau.png",
        },
        profile,
        download_intake=True,
    )

    destination = Path(result["import"]["destination"])
    assert destination.name == "Lecture 6 - Rousseau.png"
    assert destination.is_file()
    assert not staged.exists()
    assert result["target"]["id"] == "Fall 2026/POL 2103 - Politics/00_INBOX"
    activity = (Path(config["academic"]["root_directory"]) / ".academia" / "activity.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in activity.splitlines() if line.strip()]
    imported = next(event for event in events if event["event_type"] == "file.imported")
    assert imported["actor"] == "agent:chat"
    assert "token=secret" not in json.dumps(imported)
    assert "source_label" in result["import"]


def test_import_download_rejects_paths_outside_staging(tmp_path: Path) -> None:
    profile, _config, _manager, _record = connection(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 synthetic")

    with pytest.raises(mcp_server.McpError, match="download intake folder"):
        mcp_server._call_tool(
            "academia_import_download",
            {"staged_path": str(outside), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
            profile,
            download_intake=True,
        )


def test_import_download_rejects_unsupported_extensions(tmp_path: Path) -> None:
    profile, config, _manager, _record = connection(tmp_path)
    staging = runtime_directory(config) / "download_intake"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / "installer.exe"
    staged.write_bytes(b"MZ synthetic")

    with pytest.raises(mcp_server.McpError, match="supported academic extension"):
        mcp_server._call_tool(
            "academia_import_download",
            {"staged_path": str(staged), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
            profile,
            download_intake=True,
        )


def test_download_intake_accepts_a_bounded_local_upload_and_imports_it(tmp_path: Path) -> None:
    profile, config, _manager, _record = connection(tmp_path)
    info = mcp_server._call_tool("academia_download_intake", {}, profile, download_intake=True)

    request = urllib.request.Request(
        info["upload_url"],
        data=b"Lecture 7 notes",
        method="POST",
        headers={
            "X-Academia-Token": info["upload_token"],
            "X-Academia-Filename": urllib.parse.quote("Lecture 7 - Rousseau.txt"),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        uploaded = json.loads(response.read())

    staged = Path(uploaded["staged_path"])
    assert staged.is_file()
    assert staged.read_bytes() == b"Lecture 7 notes"

    result = mcp_server._call_tool(
        "academia_import_download",
        {"staged_path": str(staged), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
        profile,
        download_intake=True,
    )

    assert Path(result["import"]["destination"]).is_file()
    assert not staged.exists()


def test_download_intake_rejects_a_wrong_upload_token(tmp_path: Path) -> None:
    profile, _config, _manager, _record = connection(tmp_path)
    info = mcp_server._call_tool("academia_download_intake", {}, profile, download_intake=True)

    request = urllib.request.Request(
        info["upload_url"],
        data=b"x",
        method="POST",
        headers={"X-Academia-Token": "wrong", "X-Academia-Filename": urllib.parse.quote("x.txt")},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=10)
    assert exc_info.value.code == 403


def test_api_registry_exposes_granted_download_tools_in_course_scope(tmp_path: Path) -> None:
    from academia_os.assistant import registry
    from academia_os.assistant.contracts import ScopeKind
    from academia_os.assistant.runtime import tools_for_scope

    profile, config, _manager, record = connection(tmp_path)
    staging = runtime_directory(config) / "download_intake"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / "lecture-7.png"
    staged.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")

    context = replace(
        ReadContext.create(config),
        mcp_grants={record["id"]: frozenset({"repl"})},
        profile_path=profile,
    )
    scope = Scope(kind=ScopeKind.COURSE, semester="Fall 2026", course_id="POL 2103 - Politics")

    names = {tool["name"] for tool in tools_for_scope(scope, ToolGrant(frozenset({"download.intake", "download.import"})))}
    assert "download.intake" in names
    assert "download.import" in names

    intake = registry.invoke_granted(
        "download.intake", {}, context,
        grants=ToolGrant(frozenset({"download.intake"})), parent_scope=scope,
    )
    assert Path(intake.data["staging_directory"]).is_dir()

    with pytest.raises(AssistantError, match="browser grant"):
        registry.invoke_granted(
            "download.intake", {}, replace(context, mcp_grants={}),
            grants=ToolGrant(frozenset({"download.intake"})), parent_scope=scope,
        )

    imported = registry.invoke_granted(
        "download.import",
        {"staged_path": str(staged), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
        context,
        grants=ToolGrant(frozenset({"download.import"})),
        parent_scope=scope,
    )
    assert Path(imported.data["import"]["destination"]).is_file()
    assert not staged.exists()


def test_import_download_rejects_bytes_that_do_not_match_the_extension(tmp_path: Path) -> None:
    profile, config, _manager, _record = connection(tmp_path)
    staging = runtime_directory(config) / "download_intake"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / "login.pdf"
    staged.write_bytes(b"<html>Brightspace sign in</html>")

    with pytest.raises(mcp_server.McpError, match="declared file type"):
        mcp_server._call_tool(
            "academia_import_download",
            {"staged_path": str(staged), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
            profile,
            download_intake=True,
        )
