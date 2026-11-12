from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from academia_os.assistant import CancelToken, RunRequest, Scope
from academia_os.assistant.providers.codex_app_server import CodexAppServerRuntime
from tests.test_agent_interface import prepared_workspace

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"


def make_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "completed", auth: bool = True) -> CodexAppServerRuntime:
    config, root, profile = prepared_workspace(tmp_path)
    auth_path = tmp_path / "auth.json"
    if auth:
        auth_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    return CodexAppServerRuntime(
        academic_root=root,
        profile_path=profile,
        model="gpt-6-luna",
        codex_command=[sys.executable, str(FAKE_SERVER)],
        mcp_command=["/usr/bin/true"],
        auth_path=auth_path,
        timeout_seconds=10,
    )


def request() -> RunRequest:
    return RunRequest(messages=({"role": "user", "content": "List one Library item."},), scope=Scope(), timeout_seconds=10)


def test_completed_run_maps_mcp_tool_and_streamed_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch)
    result = runtime.run(request())

    assert result.status == "completed"
    assert result.message == "week-4-reading.md"
    assert result.error is None
    assert result.tool_results
    assert result.tool_results[0].tool == "academia_library"
    assert result.tool_results[0].data["items"][0]["name"] == "week-4-reading.md"
    event_types = [event.event_type.value for event in result.events]
    assert event_types[0] == "run_started"
    assert "tool_started" in event_types
    assert "tool_result" in event_types
    assert "message_delta" in event_types
    assert event_types[-1] == "final"
    assert any(event.data.get("delta") == "week-4-" for event in result.events if event.event_type.value == "message_delta")


def test_interrupt_maps_to_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch, mode="interrupted")
    cancel = CancelToken()
    timer = threading.Timer(0.2, cancel.cancel)
    timer.start()
    try:
        result = runtime.run(request(), cancel=cancel)
    finally:
        timer.cancel()
        timer.join(timeout=2)

    assert result.status == "cancelled"
    assert result.error is None
    assert result.events[-1].event_type.value == "cancelled"


def test_failed_turn_maps_to_structured_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch, mode="failed")
    result = runtime.run(request())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "turn_failed"
    assert "synthetic provider failure" in str(result.error)
    assert result.events[-1].event_type.value == "error"


def test_missing_auth_fails_before_starting_a_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch, auth=False)
    with pytest.raises(Exception, match="signed in"):
        runtime.run(request())


def test_read_only_mcp_command_is_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    runtime = CodexAppServerRuntime(academic_root=root, profile_path=profile, mcp_command=None)
    command = runtime._resolved_mcp_command()
    assert command[-1] == "--read-only"
    assert "mcp" in command and "serve" in command

    scoped = runtime._resolved_mcp_command(Scope(kind="course", semester="Fall 2026", course_id="POL 2103 - Politics"))
    assert scoped[-4:] == ["--semester", "Fall 2026", "--course", "POL 2103 - Politics"]

    proposal = CodexAppServerRuntime(academic_root=root, profile_path=profile, mcp_mode="proposal_only")
    assert "--proposal-only" in proposal._resolved_mcp_command()

    granted = CodexAppServerRuntime(
        academic_root=root,
        profile_path=profile,
        mcp_mode="proposal_only",
        proposal_tools=("propose_task",),
    )
    command = granted._resolved_mcp_command()
    assert command[-2:] == ["--proposal-tool", "propose_task"]
    assert "--proposal-tool" in command and "propose_import" not in command

    calendar = CodexAppServerRuntime(
        academic_root=root,
        profile_path=profile,
        mcp_mode="proposal_only",
        proposal_tools=("propose_calendar",),
    )
    assert calendar._resolved_mcp_command()[-2:] == ["--proposal-tool", "propose_calendar"]


def test_turn_carries_context_images_effort_and_fast_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = tmp_path / "turn.json"
    monkeypatch.setenv("FAKE_CODEX_CAPTURE", str(capture))
    runtime = make_runtime(tmp_path, monkeypatch)
    runtime.effort = "high"
    runtime.fast = True
    image = tmp_path / "attachment.png"
    image.write_bytes(b"not-a-real-image")
    request_with_context = RunRequest(
        messages=({"role": "user", "content": "Propose a task."},),
        scope=Scope(),
        context="COURSE CONTEXT AND ATTACHMENT TEXT",
        image_paths=(str(image),),
        timeout_seconds=10,
    )

    result = runtime.run(request_with_context)

    assert result.status == "completed"
    params = json.loads(capture.read_text(encoding="utf-8"))
    assert params["effort"] == "high"
    assert params["serviceTier"] == "fast"
    assert params["input"][0]["type"] == "text"
    assert "COURSE CONTEXT AND ATTACHMENT TEXT" in params["input"][0]["text"]
    assert params["input"][1] == {"type": "localImage", "path": str(image)}


def test_runtime_disables_shell_and_unified_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch)
    command = runtime._command()
    assert "features.shell_tool=false" in command
    assert "features.unified_exec=false" in command
    assert "features.multi_agent=false" in command
    assert 'web_search="disabled"' in command


def test_runtime_enables_live_web_search_only_when_granted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path, monkeypatch)
    granted = CodexAppServerRuntime(
        academic_root=runtime.academic_root,
        profile_path=runtime.profile_path,
        codex_command=runtime.codex_command,
        mcp_command=runtime.mcp_command,
        web_search=True,
    )
    assert 'web_search="live"' in granted._command()
    assert 'web_search="disabled"' not in granted._command()
