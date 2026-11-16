from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from academia_os.model_connections import ModelConnectionError, ModelConnectionManager


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def save(self, provider_id: str, api_key: str) -> None:
        self.values[provider_id] = api_key

    def load(self, provider_id: str) -> str | None:
        return self.values.get(provider_id)

    def delete(self, provider_id: str) -> None:
        self.values.pop(provider_id, None)


class FakeProviderServer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []
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
                headers = {key.lower(): value for key, value in self.headers.items()}
                owner.requests.append((self.path, headers))
                if self.path == "/v1/models" and headers.get("x-api-key"):
                    self._json(200, {"data": [
                        {"id": "claude-test", "display_name": "Claude Test", "type": "model"},
                    ]})
                elif self.path == "/v1/models" and headers.get("authorization") == "Bearer good-key":
                    self._json(200, {"data": [
                        {"id": "gpt-test", "object": "model"},
                        {"id": "gpt-test-mini", "object": "model"},
                    ]})
                elif self.path == "/v1/models":
                    self._json(401, {"error": "unauthorized"})
                elif self.path == "/v1beta/models" and headers.get("x-goog-api-key") == "gemini-key":
                    self._json(200, {"models": [
                        {"name": "models/gemini-test", "displayName": "Gemini Test", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/embedding-test", "supportedGenerationMethods": ["embedContent"]},
                    ]})
                elif self.path == "/api/tags":
                    self._json(200, {"models": [{"name": "llama-test:latest"}]})
                else:
                    self._json(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def test_add_providers_discovers_models_and_keeps_keys_out_of_state(tmp_path: Path) -> None:
    server = FakeProviderServer()
    credentials = MemoryCredentials()
    manager = ModelConnectionManager(tmp_path / "model_connections.json", credentials=credentials)  # type: ignore[arg-type]
    try:
        added = manager.add(provider="openai", api_key="good-key", base_url=server.origin + "/v1")
        assert added["providers"][0]["status"] == "connected"
        assert [model["id"] for model in added["providers"][0]["models"]] == ["gpt-test", "gpt-test-mini"]
        assert credentials.values["openai"] == "good-key"

        anthropic = manager.add(provider="anthropic", api_key="anthropic-key", base_url=server.origin + "/v1")
        assert anthropic["providers"][1]["models"][0]["id"] == "claude-test"
        assert "vision" in anthropic["providers"][1]["models"][0]["capabilities"]

        gemini = manager.add(provider="gemini", api_key="gemini-key", base_url=server.origin + "/v1beta")
        assert [model["id"] for model in gemini["providers"][2]["models"]] == ["gemini-test"]

        ollama = manager.add(provider="ollama", base_url=server.origin)
        assert ollama["providers"][3]["models"][0]["id"] == "llama-test:latest"

        state_text = (tmp_path / "model_connections.json").read_text(encoding="utf-8")
        assert "good-key" not in state_text
        assert "anthropic-key" not in state_text
        assert "gemini-key" not in state_text

        preferences = manager.set_preferences({"default": "openai/gpt-test", "fast": "openai/gpt-test-mini", "deep": "anthropic/claude-test"})
        assert preferences["preferences"]["default"] == "openai/gpt-test"
        with pytest.raises(ModelConnectionError, match="enabled provider models"):
            manager.set_preferences({"default": "openai/missing"})

        removed = manager.remove("openai")
        assert all(item["id"] != "openai" for item in removed["providers"])
        assert removed["preferences"]["default"] is None
        assert "openai" not in credentials.values
    finally:
        server.close()


def test_bad_key_fails_closed_and_does_not_persist(tmp_path: Path) -> None:
    server = FakeProviderServer()
    credentials = MemoryCredentials()
    manager = ModelConnectionManager(tmp_path / "model_connections.json", credentials=credentials)  # type: ignore[arg-type]
    try:
        with pytest.raises(ModelConnectionError, match="rejected"):
            manager.add(provider="openai", api_key="bad-key", base_url=server.origin + "/v1")
        assert manager.list()["providers"] == []
        assert credentials.values == {}
    finally:
        server.close()


def test_catalog_lists_added_api_providers(tmp_path: Path) -> None:
    manager = ModelConnectionManager(tmp_path / "model_connections.json", credentials=MemoryCredentials())  # type: ignore[arg-type]
    catalog = {entry["id"]: entry for entry in manager.catalog()}
    for provider_id in ("xai", "opencode-zen", "opencode-go", "together", "cerebras", "moonshot", "zai"):
        assert provider_id in catalog
        assert catalog[provider_id]["kind"] == "api"
        assert catalog[provider_id]["default_base_url"].startswith("https://")
    assert catalog["xai"]["default_base_url"] == "https://api.x.ai/v1"
    assert catalog["opencode-zen"]["default_base_url"] == "https://opencode.ai/zen/v1"
    assert catalog["opencode-go"]["default_base_url"] == "https://opencode.ai/zen/go/v1"


def test_zen_models_exclude_other_protocols() -> None:
    from academia_os.model_connections import _normalize_models

    payload = {
        "data": [
            {"id": "glm-5", "name": "GLM 5", "type": "chat", "api": {"chat-completions": {"base_url": "https://opencode.ai/zen/v1"}}},
            {"id": "gpt-5.2", "name": "GPT 5.2", "type": "chat", "api": {"responses": {"base_url": "https://opencode.ai/zen/v1/responses"}}},
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "type": "chat", "api": {"messages": {"base_url": "https://opencode.ai/zen/v1/messages"}}},
            {"id": "gemini-3-pro", "name": "Gemini 3 Pro", "type": "chat", "api": {"google": {"base_url": "https://opencode.ai/zen/v1/models/gemini-3-pro"}}},
            {"id": "text-embedding-3", "name": "Embedding", "type": "embedding", "api": {}},
            {"id": "kimi-k2.5", "name": "Kimi K2.5", "type": "chat", "api": {"chat-completions": {"base_url": "https://opencode.ai/zen/v1"}}},
        ]
    }
    models = _normalize_models("opencode-zen", payload)
    assert [item["id"] for item in models] == ["glm-5", "kimi-k2.5"]


def test_opencode_go_keeps_translated_models_and_sends_session_header() -> None:
    from academia_os.model_connections import _normalize_models, _opencode_headers

    payload = {
        "data": [
            {"id": "glm-5.3", "name": "GLM 5.3", "type": "chat", "api": {"chat-completions": {}}},
            {"id": "grok-4.7", "name": "Grok 4.7", "type": "chat", "api": {"responses": {}}},
            {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5", "type": "chat", "api": {"messages": {}}},
            {"id": "embed-1", "name": "Embedding", "type": "embedding", "api": {}},
        ]
    }
    assert [item["id"] for item in _normalize_models("opencode-go", payload)] == [
        "claude-haiku-5-5",
        "glm-5.3",
        "grok-4.7",
    ]
    assert _opencode_headers("opencode-go", "abc") == {"x-opencode-session": "abc"}
    assert _opencode_headers("opencode-zen") == {}
    assert _opencode_headers("openai") == {}
