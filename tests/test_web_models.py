from __future__ import annotations

import json
from pathlib import Path

from academia_os.model_connections import ModelConnectionManager
from tests.test_model_connections import FakeProviderServer, MemoryCredentials
from tests.test_web import request, running_server


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_model_provider_web_routes(tmp_path: Path) -> None:
    remote = FakeProviderServer()
    try:
        with running_server(tmp_path) as web:
            web.model_manager = ModelConnectionManager(tmp_path / "runtime" / "model_connections.json", credentials=MemoryCredentials())  # type: ignore[arg-type]

            status, _, payload = request(web, "GET", "/api/v1/models")
            assert status == 200
            assert json.loads(payload)["providers"] == []
            assert any(item["id"] == "openai" for item in json.loads(payload)["catalog"])

            status, _, payload = post(web, "/api/v1/models/add", {
                "provider": "openai",
                "api_key": "good-key",
                "base_url": remote.origin + "/v1",
            })
            assert status == 200
            connected = json.loads(payload)
            assert connected["providers"][0]["models"][0]["id"] == "gpt-test"

            status, _, payload = post(web, "/api/v1/models/set-preferences", {"default": "openai/gpt-test", "fast": None, "deep": None, "vision": None, "image": None})
            assert status == 200
            assert json.loads(payload)["preferences"]["default"] == "openai/gpt-test"

            status, _, payload = post(web, "/api/v1/models/test", {"provider": "openai"})
            assert status == 200
            assert json.loads(payload)["providers"][0]["status"] == "connected"

            status, _, payload = post(web, "/api/v1/models/disable", {"provider": "openai"})
            assert status == 200
            assert json.loads(payload)["providers"][0]["enabled"] is False

            status, _, payload = post(web, "/api/v1/models/remove", {"provider": "openai"})
            assert status == 200
            assert json.loads(payload)["providers"] == []
    finally:
        remote.close()


def test_model_provider_web_rejects_bad_key(tmp_path: Path) -> None:
    remote = FakeProviderServer()
    try:
        with running_server(tmp_path) as web:
            web.model_manager = ModelConnectionManager(tmp_path / "runtime" / "model_connections.json", credentials=MemoryCredentials())  # type: ignore[arg-type]
            status, _, payload = post(web, "/api/v1/models/add", {
                "provider": "openai",
                "api_key": "bad-key",
                "base_url": remote.origin + "/v1",
            })
            assert status == 422
            assert json.loads(payload)["type"] == "ModelConnectionError"
    finally:
        remote.close()
