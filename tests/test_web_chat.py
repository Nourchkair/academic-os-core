from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from academia_os import dashboard_chat
from tests.test_web import request, running_server


def post_chat(server: Any, body: bytes, *, content_type: str = "application/json") -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", "/api/v1/chat", body=body, headers={"Content-Type": content_type})


def test_chat_providers_endpoint_returns_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard_chat, "providers", lambda: {"default_provider": "codex", "providers": [{"id": "codex"}]})
    with running_server(tmp_path) as server:
        status, headers, payload = request(server, "GET", "/api/v1/chat/providers")

    assert status == 200
    assert headers["content-type"].startswith("application/json")
    assert json.loads(payload) == {"default_provider": "codex", "providers": [{"id": "codex"}]}


def test_chat_providers_endpoint_falls_back_when_detection_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> dict[str, Any]:
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
