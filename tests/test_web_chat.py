from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from academia_os import dashboard_chat
from academia_os.assistant.providers.base import CancelToken
from tests.test_web import request, running_server


def post_chat(server: Any, body: bytes, *, content_type: str = "application/json") -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", "/api/v1/chat", body=body, headers={"Content-Type": content_type})


def test_chat_providers_endpoint_returns_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_chat, "providers", lambda profile=None: {"default_provider": "codex", "providers": [{"id": "codex"}]})
    with running_server(tmp_path) as server:
        status, headers, payload = request(server, "GET", "/api/v1/chat/providers")

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(payload) == {"default_provider": "codex", "providers": [{"id": "codex"}]}


def test_chat_providers_endpoint_falls_back_when_detection_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(profile: Path | None = None) -> dict[str, Any]:
        raise OSError("provider lookup failed")

    monkeypatch.setattr(dashboard_chat, "providers", fail)
    with running_server(tmp_path) as server:
        status, _, payload = request(server, "GET", "/api/v1/chat/providers")

    assert status == 200
    value = json.loads(payload)
    assert value["available"] is False
    assert value["models"] == []
    assert value["provider"] == "Codex CLI using ChatGPT sign-in"


def test_chat_route_passes_exact_payload_and_returns_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def respond(payload: dict[str, Any], *, profile: Path | None = None) -> dict[str, Any]:
        captured.update(payload)
        return {"message": "answer", "provider": "codex", "model": "test", "effort": "medium", "speed": "standard", "notice": None}

    monkeypatch.setattr(dashboard_chat, "respond", respond)
    body = json.dumps({"messages": [{"role": "user", "content": "hello"}], "provider": "codex"}).encode("utf-8")
    with running_server(tmp_path) as server:
        status, headers, payload = post_chat(server, body)

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(payload)["message"] == "answer"
    assert captured == {"messages": [{"role": "user", "content": "hello"}], "provider": "codex"}


def test_chat_route_maps_value_error_to_structured_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(payload: dict[str, Any], *, profile: Path | None = None) -> dict[str, Any]:
        raise ValueError("Codex is not signed in")

    monkeypatch.setattr(dashboard_chat, "respond", respond)
    with running_server(tmp_path) as server:
        status, _, payload = post_chat(server, json.dumps({"messages": []}).encode("utf-8"))

    assert status == 422
    value = json.loads(payload)
    assert value == {"error": "Codex is not signed in", "type": "ChatError"}


def test_chat_route_maps_provider_failure_to_structured_502(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(payload: dict[str, Any], *, profile: Path | None = None) -> dict[str, Any]:
        raise OSError("provider unavailable")

    monkeypatch.setattr(dashboard_chat, "respond", respond)
    with running_server(tmp_path) as server:
        status, _, payload = post_chat(server, json.dumps({"messages": []}).encode("utf-8"))

    assert status == 502
    value = json.loads(payload)
    assert value == {"error": "Codex could not complete this chat request", "type": "ChatUnavailable"}


def test_chat_route_requires_json_content_type(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        status, _, payload = post_chat(server, b"{}", content_type="text/plain")

    assert status == 415
    assert json.loads(payload)["type"] == "UnsupportedMediaType"


def test_chat_route_rejects_malformed_json_without_calling_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def respond(payload: dict[str, Any], *, profile: Path | None = None) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(dashboard_chat, "respond", respond)
    with running_server(tmp_path) as server:
        status, _, payload = post_chat(server, b"{")

    assert status == 400
    assert json.loads(payload)["type"] == "MalformedJSON"
    assert called is False


def test_chat_route_is_not_available_over_get(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        status, _, payload = request(server, "GET", "/api/v1/chat")

    assert status == 404
    assert json.loads(payload)["type"] == "NotFound"


def post_stream(server: Any, body: bytes) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", "/api/v1/chat/stream", body=body, headers={"Content-Type": "application/json"})


def post_cancel(server: Any, body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", "/api/v1/chat/cancel", body=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_chat_stream_route_returns_ndjson_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stream_chat(payload: dict[str, Any], *, profile: Path, run_id: str, cancel: CancelToken, emit: Any) -> None:
        emit({"type": "started", "run_id": run_id, "model": "test-model"})
        emit({"type": "tool_started", "tool": "academia_propose_task", "call_id": "call-1"})
        emit({"type": "proposal", "proposal": {"kind": "task", "review_id": "review-1"}})
        emit({"type": "final", "message": "Prepared a proposal.", "proposals": [{"review_id": "review-1"}]})

    monkeypatch.setattr(dashboard_chat, "stream_chat", stream_chat)
    body = json.dumps({"messages": [{"role": "user", "content": "hello"}], "proposal_mode": True}).encode("utf-8")
    with running_server(tmp_path) as server:
        status, headers, payload = post_stream(server, body)

    assert status == 200
    assert headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    assert [event["type"] for event in events] == ["started", "tool_started", "proposal", "final"]
    assert events[0]["run_id"]


def test_chat_cancel_route_cancels_an_active_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stream_chat(payload: dict[str, Any], *, profile: Path, run_id: str, cancel: CancelToken, emit: Any) -> None:
        emit({"type": "started", "run_id": run_id})
        for _ in range(50):
            if cancel.cancelled:
                emit({"type": "cancelled"})
                return
            time.sleep(0.01)
        emit({"type": "final", "message": "late", "proposals": []})

    monkeypatch.setattr(dashboard_chat, "stream_chat", stream_chat)
    body = json.dumps({"messages": [{"role": "user", "content": "hello"}], "proposal_mode": True}).encode("utf-8")
    with running_server(tmp_path) as server:
        result: dict[str, Any] = {}

        def run_stream() -> None:
            result["value"] = post_stream(server, body)

        thread = threading.Thread(target=run_stream)
        thread.start()
        deadline = time.monotonic() + 2
        while not server.chat_runs and time.monotonic() < deadline:
            time.sleep(0.01)
        run_id = next(iter(server.chat_runs))
        status, _, payload = post_cancel(server, {"run_id": run_id})
        thread.join(timeout=5)

    assert status == 200
    assert json.loads(payload)["cancelled"] is True
    events = [json.loads(line) for line in result["value"][2].decode("utf-8").splitlines() if line.strip()]
    assert events[-1]["type"] == "cancelled"


def test_chat_cancel_route_reports_unknown_run(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        status, _, payload = post_cancel(server, {"run_id": "missing"})
    assert status == 200
    assert json.loads(payload) == {"run_id": "missing", "cancelled": False}
