from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from academia_os import dashboard_chat
from academia_os.dashboard_chat import _validate_payload, respond
from academia_os.study.providers import CLAUDE_UNAVAILABLE_NOTICE


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
    prompt, provider, model, effort, fast, attachments, context = _validate_payload(payload())

    assert prompt == "USER: hello"
    assert provider == "codex"
    assert model is None
    assert effort == "medium"
    assert fast is False
    assert attachments == []
    assert context == ""


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
    _, _, _, _, _, attachments, _ = _validate_payload(
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
