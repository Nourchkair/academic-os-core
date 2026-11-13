from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from academia_os import dashboard_chat
from academia_os.assistant.contracts import AssistantError, EventType, RunEvent, RunResult, ToolResult
from academia_os.assistant.providers.base import CancelToken, ProviderResponse
from academia_os.dashboard_chat import _proposal_card, _proposal_instruction, _validate_payload, respond, stream_chat
from academia_os.study.providers import CLAUDE_UNAVAILABLE_NOTICE
from tests.test_agent_interface import prepared_workspace


def message(content: str = "hello", role: str = "user") -> dict[str, str]:
    return {"role": role, "content": content}


def payload(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"messages": [message()], "provider": "codex"}
    value.update(overrides)
    return value


def available_catalog() -> dict[str, Any]:
    return {
        "default_provider": "codex",
        "providers": [
            {
                "id": "codex",
                "name": "Codex",
                "available": True,
                "notice": "",
                "models": [{"id": "test-model", "name": "Test Model"}],
            }
        ],
    }


def test_validate_payload_accepts_minimal_codex_chat() -> None:
    prompt, messages, provider, model, effort, fast, attachments, context, proposal_mode, course_id, semester, grants, web_search, connector_grants = _validate_payload(payload())

    assert prompt == "USER: hello"
    assert messages == [{"role": "user", "content": "hello"}]
    assert provider == "codex"
    assert model is None
    assert effort == "medium"
    assert fast is False
    assert attachments == []
    assert context == ""
    assert proposal_mode is False
    assert course_id is None
    assert semester is None
    assert grants == []
    assert web_search is False
    assert connector_grants == []


def test_validate_payload_requires_explicit_boolean_web_search() -> None:
    assert _validate_payload(payload(web_search=True))[-2] is True
    with pytest.raises(ValueError, match="web_search"):
        _validate_payload(payload(web_search="yes"))


def test_validate_payload_accepts_bounded_google_connector_grants() -> None:
    assert _validate_payload(payload(connector_grants=["gmail", "calendar"]))[-1] == ["gmail", "calendar"]
    with pytest.raises(ValueError, match="connector_grants"):
        _validate_payload(payload(connector_grants=["gmail", "drive"]))


def test_calendar_proposal_grant_is_explicit_and_creates_a_review_card() -> None:
    instruction = _proposal_instruction(["calendar"])
    assert "academia_propose_calendar" in instruction
    assert "Never call direct write tools" in instruction
    assert "requires explicit timezone" in instruction or "timezone" in instruction
    card = _proposal_card("academia_propose_calendar", {
        "action": "create",
        "review_id": "review-calendar",
        "proposal_id": "proposal-calendar",
        "after": "Study block\n2027-02-10T14:00:00Z – 2027-02-10T15:00:00Z",
        "effects": ["Create one Google Calendar event after approval."],
    })
    assert card is not None
    assert card["kind"] == "calendar"
    assert card["review_id"] == "review-calendar"


def test_validate_payload_bounds_messages_and_prompt_size() -> None:
    with pytest.raises(ValueError, match="1–20"):
        _validate_payload(payload(messages=[message() for _ in range(21)]))

    huge = [message("x" * 12_000) for _ in range(6)]
    with pytest.raises(ValueError, match="60,000"):
        _validate_payload(payload(messages=huge))

    with pytest.raises(ValueError, match="user or assistant"):
        _validate_payload(payload(messages=[{"role": "system", "content": "no"}]))

    with pytest.raises(ValueError, match="text content"):
        _validate_payload(payload(messages=[{"role": "user", "content": 5}]))


def test_validate_payload_rejects_unsupported_provider_effort_and_speed() -> None:
    with pytest.raises(ValueError, match="Codex"):
        _validate_payload(payload(provider="other"))
    with pytest.raises(ValueError, match="reasoning"):
        _validate_payload(payload(effort="impossible"))
    with pytest.raises(ValueError, match="speed"):
        _validate_payload(payload(speed="ludicrous"))


def test_validate_payload_bounds_course_context_and_model_name() -> None:
    with pytest.raises(ValueError, match="selected course context"):
        _validate_payload(payload(course_context="x" * (dashboard_chat.MAX_CHAT_CONTEXT_CHARS + 1)))
    with pytest.raises(ValueError, match="model"):
        _validate_payload(payload(model="m" * 201))


def test_validate_payload_accepts_supported_attachment_metadata() -> None:
    raw = b"# notes\n"
    encoded = base64.b64encode(raw).decode("ascii")
    _, _, _, _, _, _, attachments, *_ = _validate_payload(
        payload(attachments=[{"name": "../notes.md", "type": "text/markdown", "data": encoded}])
    )

    assert attachments == [{"name": "notes.md", "type": "text/markdown", "data": encoded}]


def test_validate_payload_rejects_invalid_attachment_forms() -> None:
    good = base64.b64encode(b"data").decode("ascii")
    with pytest.raises(ValueError, match="five"):
        _validate_payload(payload(attachments=[{"name": f"{index}.md", "type": "text/markdown", "data": good} for index in range(6)]))
    with pytest.raises(ValueError, match="PDF, DOCX"):
        _validate_payload(payload(attachments=[{"name": "run.exe", "type": "application/octet-stream", "data": good}]))
    with pytest.raises(ValueError, match="base64"):
        _validate_payload(payload(attachments=[{"name": "notes.md", "type": "text/markdown", "data": "not base64"}]))
    with pytest.raises(ValueError, match="PDF, DOCX"):
        _validate_payload(payload(attachments=[{"name": "notes.md", "type": "image/png", "data": good}]))
    with pytest.raises(ValueError, match="under 12 MB"):
        _validate_payload(payload(attachments=[{"name": "notes.md", "type": "text/markdown", "data": base64.b64encode(b"x" * (dashboard_chat.MAX_ATTACHMENT_BYTES + 1)).decode("ascii")}]))


def test_respond_rejects_claude_with_anthropic_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)

    with pytest.raises(ValueError, match="Claude subscription sign-in cannot be routed"):
        respond(payload(provider="claude"))


def test_respond_rejects_unavailable_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dashboard_chat,
        "provider_catalog",
        lambda: {"providers": [{"id": "codex", "name": "Codex", "available": False, "notice": "Sign in first."}]},
    )

    with pytest.raises(ValueError, match="Sign in first"):
        respond(payload())


def test_respond_runs_constrained_codex_and_returns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        captured["input"] = kwargs["input"]
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("A grounded answer.", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: ("test-model", None))
    monkeypatch.setattr(dashboard_chat.subprocess, "run", fake_run)

    result = respond(payload(course_context="COURSE CONTEXT", effort="high", speed="fast"))

    assert result == {
        "message": "A grounded answer.",
        "provider": "codex",
        "model": "test-model",
        "effort": "high",
        "speed": "fast",
        "notice": None,
    }
    command = captured["command"]
    assert command[0] == "/fake/codex"
    assert "--ephemeral" in command
    assert "--sandbox" in command and command[command.index("--sandbox") + 1] == "read-only"
    assert "features.shell_tool=false" in command
    assert "features.unified_exec=false" in command
    assert "features.multi_agent=false" in command
    assert "features.apps=false" in command
    assert "features.plugins=false" in command
    assert 'web_search="disabled"' in command
    assert 'model_reasoning_effort="high"' in command
    assert 'service_tier="fast"' in command
    assert "--model" in command and command[command.index("--model") + 1] == "test-model"
    assert "COURSE CONTEXT" in captured["input"]
    assert "OPENAI_API_KEY" not in captured["environment"]


def test_respond_enables_live_web_search_only_with_the_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("Searched answer.", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: ("test-model", None))
    monkeypatch.setattr(dashboard_chat.subprocess, "run", fake_run)

    respond(payload(web_search=True))
    assert 'web_search="live"' in captured["command"]
    assert 'web_search="disabled"' not in captured["command"]


def test_respond_uses_a_configured_api_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    class FakeCredentials:
        def load(self, provider_id: str) -> str:
            return "api-key"

    class FakeManager:
        credentials = FakeCredentials()

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def list(self) -> dict[str, Any]:
            return {
                "providers": [{
                    "id": "openai",
                    "name": "OpenAI",
                    "status": "connected",
                    "enabled": True,
                    "base_url": "https://api.openai.com/v1",
                    "auth": "configured",
                    "models": [{"id": "gpt-test", "name": "GPT Test", "capabilities": ["chat"]}],
                }],
                "preferences": {"default": None, "fast": None, "deep": None, "vision": None, "image": None},
            }

    class FakeAdapter:
        id = "api:openai"

        def complete(self, request: Any, *, cancel: Any = None) -> ProviderResponse:
            assert "STUDENT-SELECTED" in request.context or "study assistant" in request.context
            return ProviderResponse(text="API answer")

    monkeypatch.setattr(dashboard_chat, "ModelConnectionManager", FakeManager)
    monkeypatch.setattr(dashboard_chat, "_api_adapter", lambda record, key, model: FakeAdapter())

    result = respond(payload(provider="api:openai", model="gpt-test"), profile=profile)
    assert result["message"] == "API answer"
    assert result["provider"] == "api:openai"
    assert result["model"] == "gpt-test"
    assert result["notice"] is None

    with pytest.raises(ValueError, match="require Codex"):
        _validate_payload(payload(provider="api:openai", proposal_mode=True, granted_proposal_tools=["task"]))


def test_respond_runs_api_provider_read_tools_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    from tests.test_api_providers import FakeChatServer
    from tests.test_model_connections import MemoryCredentials
    from academia_os.model_connections import ModelConnectionManager

    server = FakeChatServer()
    manager = ModelConnectionManager(tmp_path / "model_connections.json", credentials=MemoryCredentials())  # type: ignore[arg-type]
    try:
        manager.add(provider="openai", api_key="key", base_url=server.origin + "/v1")
        monkeypatch.setattr(dashboard_chat, "ModelConnectionManager", lambda _path: manager)
        result = respond(payload(provider="api:openai", model="gpt-test"), profile=profile)
        assert result["message"] == "API final answer"
        assert result["provider"] == "api:openai"
        assert any(message.get("role") == "tool" for message in server.openai_bodies[-1]["messages"])
    finally:
        server.close()


def test_provider_catalog_includes_connected_api_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    class FakeCredentials:
        def load(self, provider_id: str) -> str:
            return "api-key"

    class FakeManager:
        credentials = FakeCredentials()

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def list(self) -> dict[str, Any]:
            return {
                "providers": [{
                    "id": "openai",
                    "name": "OpenAI",
                    "status": "connected",
                    "enabled": True,
                    "base_url": "https://api.openai.com/v1",
                    "auth": "configured",
                    "models": [{"id": "gpt-test", "name": "GPT Test", "capabilities": ["chat"]}],
                }],
                "preferences": {"default": "openai/gpt-test", "fast": None, "deep": None, "vision": None, "image": None},
            }

    monkeypatch.setattr(dashboard_chat, "ModelConnectionManager", FakeManager)
    catalog = dashboard_chat.providers(profile)
    api = next(entry for entry in catalog["providers"] if entry["id"] == "api:openai")
    assert api["models"][0]["id"] == "gpt-test"
    assert api["billing"] == "api"


def test_respond_reports_plan_limit_and_generic_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))

    def limited(command: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="usage limit reached")

    monkeypatch.setattr(dashboard_chat.subprocess, "run", limited)
    with pytest.raises(ValueError, match="plan usage is currently limited"):
        respond(payload())

    def failed(command: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="unknown failure")

    monkeypatch.setattr(dashboard_chat.subprocess, "run", failed)
    with pytest.raises(ValueError, match="could not answer"):
        respond(payload())


def test_respond_reports_timeout_and_empty_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))

    def timeout(command: list[str], **kwargs: Any) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(command, dashboard_chat.CHAT_TIMEOUT)

    monkeypatch.setattr(dashboard_chat.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        respond(payload())

    def empty(command: list[str], **kwargs: Any) -> SimpleNamespace:
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dashboard_chat.subprocess, "run", empty)
    with pytest.raises(ValueError, match="empty response"):
        respond(payload())


def test_validate_payload_accepts_and_bounds_proposal_scope() -> None:
    *_, proposal_mode, course_id, semester, grants, web_search, connector_grants = _validate_payload(
        payload(proposal_mode=True, course_id="POL 2103", semester="Fall 2026")
    )
    assert proposal_mode is True
    assert course_id == "POL 2103"
    assert semester == "Fall 2026"
    assert grants == ["task", "import"]

    *_, grants, web_search, connector_grants = _validate_payload(payload(proposal_mode=True, granted_proposal_tools=["task"]))
    assert grants == ["task"]
    with pytest.raises(ValueError, match="at least one"):
        _validate_payload(payload(proposal_mode=True, granted_proposal_tools=[]))
    assert _validate_payload(payload(proposal_mode=True, granted_proposal_tools=["calendar"]))[-3] == ["calendar"]
    with pytest.raises(ValueError, match="granted_proposal_tools"):
        _validate_payload(payload(proposal_mode=True, granted_proposal_tools=["drive"]))

    with pytest.raises(ValueError, match="proposal_mode"):
        _validate_payload(payload(proposal_mode="yes"))
    with pytest.raises(ValueError, match="action proposals require Codex"):
        _validate_payload(payload(proposal_mode=True, provider="claude"))
    with pytest.raises(ValueError, match="course_id"):
        _validate_payload(payload(proposal_mode=True, course_id=5))
    with pytest.raises(ValueError, match="term and four-digit year"):
        _validate_payload(payload(proposal_mode=True, semester="Current Semester"))


def test_respond_proposal_mode_uses_app_server_and_returns_cards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    captured: dict[str, Any] = {}

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs

        def run(self, request: Any, **kwargs: Any) -> RunResult:
            captured["request"] = request
            return RunResult(
                run_id="run-1",
                status="completed",
                message="I prepared a task proposal for your review. Nothing has been approved or changed.",
                tool_results=(ToolResult(
                    tool="academia_propose_task",
                    data={
                        "status": "approval_required",
                        "action": "create",
                        "proposal_id": "proposal-1",
                        "review_id": "review-1",
                        "before": "No personal task",
                        "after": "Read Week 5 · POL 2103 - Politics · due 2026-10-01",
                        "effects": ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md", "preserve unrelated Markdown"],
                    },
                ),),
            )

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: ("test-model", None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FakeRuntime)
    attachment = base64.b64encode(b"# Reading list\nRead Week 5\n").decode("ascii")

    result = respond(
        payload(
            proposal_mode=True,
            course_id="POL 2103",
            semester="Fall 2026",
            effort="high",
            speed="fast",
            course_context="COURSE CONTEXT",
            attachments=[{"name": "notes.md", "type": "text/markdown", "data": attachment}],
        ),
        profile=profile,
    )

    assert result["proposal_mode"] is True
    assert result["proposals"] == [{
        "kind": "task",
        "title": "Personal task proposal",
        "summary": "Read Week 5 · POL 2103 - Politics · due 2026-10-01",
        "effects": ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md", "preserve unrelated Markdown"],
        "review_id": "review-1",
        "proposal_id": "proposal-1",
    }]
    assert captured["init"]["mcp_mode"] == "proposal_only"
    assert captured["init"]["proposal_tools"] == ("propose_task", "propose_import")
    assert captured["init"]["model"] == "test-model"
    assert captured["init"]["effort"] == "high"
    assert captured["init"]["fast"] is True
    assert captured["request"].scope.as_dict() == {
        "kind": "course",
        "semester": "Fall 2026",
        "course_id": "POL 2103 - Politics",
    }
    assert captured["request"].messages == ({"role": "user", "content": "hello"},)
    assert "COURSE CONTEXT" in captured["request"].context
    assert "PROPOSAL-ONLY MODE" in captured["request"].context
    assert "REFERENCE MD notes.md" in captured["request"].context
    assert captured["request"].image_paths == ()


def test_respond_proposal_mode_rejects_unknown_course_and_runtime_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))

    with pytest.raises(ValueError, match="recognized course"):
        respond(payload(proposal_mode=True, course_id="NOPE 101", semester="Fall 2026"), profile=profile)

    class FailedRuntime:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, request: Any, **kwargs: Any) -> RunResult:
            return RunResult(
                run_id="run-1",
                status="error",
                error=AssistantError(
                    '{"type":"error","error":{"message":"Unsupported value: minimal is not supported","type":"invalid_request_error"}}',
                    code="provider_error",
                ),
            )

    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FailedRuntime)
    with pytest.raises(ValueError, match="Unsupported value: minimal is not supported"):
        respond(payload(proposal_mode=True, semester="Fall 2026"), profile=profile)


def test_respond_proposal_mode_maps_minimal_effort_to_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    captured: dict[str, Any] = {}

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def run(self, request: Any, **kwargs: Any) -> RunResult:
            return RunResult(run_id="run-1", status="completed", message="ready")

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FakeRuntime)

    result = respond(payload(proposal_mode=True, semester="Fall 2026", effort="minimal"), profile=profile)

    assert captured["effort"] == "low"
    assert result["effort"] == "low"


def test_respond_proposal_mode_bounds_oversized_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    captured: dict[str, Any] = {}

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, request: Any, **kwargs: Any) -> RunResult:
            captured["request"] = request
            return RunResult(run_id="run-1", status="completed", message="ready")

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FakeRuntime)

    respond(payload(proposal_mode=True, semester="Fall 2026", course_context="x" * dashboard_chat.MAX_CHAT_CONTEXT_CHARS), profile=profile)

    request = captured["request"]
    assert len(request.context) <= 240_000
    assert "Additional selected context was truncated" in request.context
    assert "PROPOSAL-ONLY MODE" in request.context


def test_stream_chat_emits_tool_progress_proposal_and_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    proposal_data = {
        "status": "approval_required",
        "action": "create",
        "proposal_id": "proposal-1",
        "review_id": "review-1",
        "before": "No personal task",
        "after": "Read Week 5 · POL 2103 - Politics · due 2026-10-01",
        "effects": ["add 'Read Week 5' to Fall 2026/SEMESTER_TASKS.md"],
    }

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, request: Any, *, cancel: Any = None, on_event: Any = None) -> RunResult:
            if on_event is not None:
                on_event(RunEvent(run_id="r", sequence=0, event_type=EventType.TOOL_STARTED, data={"name": "academia_propose_task", "call_id": "call-1"}))
                on_event(RunEvent(run_id="r", sequence=1, event_type=EventType.TOOL_RESULT, data={"name": "academia_propose_task", "call_id": "call-1", "ok": True, "data": proposal_data}))
                on_event(RunEvent(run_id="r", sequence=2, event_type=EventType.MESSAGE_DELTA, data={"delta": "Prepared a task proposal."}))
            return RunResult(
                run_id="r",
                status="completed",
                message="Prepared a task proposal.",
                tool_results=(ToolResult(tool="academia_propose_task", data=proposal_data),),
            )

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: ("test-model", None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FakeRuntime)
    events: list[dict[str, Any]] = []

    stream_chat(
        payload(proposal_mode=True, semester="Fall 2026", course_id="POL 2103"),
        profile=profile,
        run_id="run-1",
        cancel=CancelToken(),
        emit=events.append,
    )

    assert [event["type"] for event in events] == ["started", "tool_started", "tool_result", "proposal", "delta", "final"]
    assert events[0]["run_id"] == "run-1"
    assert events[1]["tool"] == "academia_propose_task"
    assert events[3]["proposal"]["review_id"] == "review-1"
    assert events[4]["delta"] == "Prepared a task proposal."
    assert events[5]["proposals"][0]["review_id"] == "review-1"


def test_stream_chat_reports_granted_google_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    captured: dict[str, Any] = {}

    class FakeRuntime:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, request: Any, *, cancel: Any = None, on_event: Any = None) -> RunResult:
            captured["context"] = request.context
            return RunResult(run_id="r", status="completed", message="Used Google context.")

    monkeypatch.setattr(dashboard_chat, "_google_context", lambda profile, grants: "GOOGLE CONTEXT MARKER")
    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: ("test-model", None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", FakeRuntime)
    events: list[dict[str, Any]] = []

    stream_chat(
        payload(proposal_mode=True, semester="Fall 2026", course_id="POL 2103", connector_grants=["gmail"]),
        profile=profile,
        run_id="run-google",
        cancel=CancelToken(),
        emit=events.append,
    )

    assert [event["type"] for event in events] == ["started", "tool_started", "tool_result", "final"]
    assert events[1]["tool"] == "academia_google_context"
    assert "GOOGLE CONTEXT MARKER" in captured["context"]


def test_google_context_reads_only_granted_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    class FakeConnector:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def status(self) -> dict[str, Any]:
            return {"auth_status": "authorized", "account_email": "student@example.edu"}

        def gmail_list(self, *, max_results: int = 5) -> dict[str, Any]:
            return {"messages": [{"date": "Mon, 10 Nov 2026", "from": "advisor@example.edu", "subject": "Essay extension", "snippet": "You may submit on Friday."}]}

        def calendar_list(self, *, time_max: str | None = None, max_results: int = 10) -> dict[str, Any]:
            return {"events": [{"id": "event-1", "start": {"dateTime": "2026-11-12T10:00:00-05:00"}, "end": {"dateTime": "2026-11-12T11:00:00-05:00"}, "summary": "Office hours", "location": "Room 203"}]}

    from academia_os.connectors import google as google_module
    monkeypatch.setattr(google_module, "GoogleConnector", FakeConnector)
    text = dashboard_chat._google_context(profile, ["gmail", "calendar"])
    assert "Essay extension" in text
    assert "Office hours" in text
    assert "student@example.edu" in text
    assert "event id: event-1" in text

    class UnauthorizedConnector(FakeConnector):
        def status(self) -> dict[str, Any]:
            return {"auth_status": "configured", "account_email": None}

    monkeypatch.setattr(google_module, "GoogleConnector", UnauthorizedConnector)
    with pytest.raises(ValueError, match="Connect Google"):
        dashboard_chat._google_context(profile, ["gmail"])


def test_stream_chat_reports_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    class CancelledRuntime:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, request: Any, *, cancel: Any = None, on_event: Any = None) -> RunResult:
            assert cancel is not None
            cancel.cancel()
            return RunResult(run_id="r", status="cancelled")

    monkeypatch.setattr(dashboard_chat, "provider_catalog", available_catalog)
    monkeypatch.setattr(dashboard_chat, "codex_runtime", lambda: {"executable": "/fake/codex", "models": [], "recommended_model": None})
    monkeypatch.setattr(dashboard_chat, "codex_model", lambda runtime, requested: (None, None))
    monkeypatch.setattr(dashboard_chat, "CodexAppServerRuntime", CancelledRuntime)
    events: list[dict[str, Any]] = []

    stream_chat(payload(proposal_mode=True, semester="Fall 2026"), profile=profile, run_id="run-1", cancel=CancelToken(), emit=events.append)

    assert [event["type"] for event in events] == ["started", "cancelled"]


def test_proposal_card_names_an_import_source() -> None:
    card = dashboard_chat._proposal_card("academia_propose_import", {
        "review_id": "review-1",
        "proposal_id": "proposal-1",
        "source_path": "/tmp/lecture-notes.md",
        "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX",
        "effects": ["copy lecture-notes.md"],
    })
    assert card is not None
    assert card["summary"] == "Copy lecture-notes.md into Fall 2026/POL 2103 - Politics/00_INBOX"
