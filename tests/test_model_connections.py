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
