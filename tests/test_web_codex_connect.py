from __future__ import annotations

import json
import os
from pathlib import Path

from tests.test_web import request, running_server


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_codex_connection_routes(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    with running_server(tmp_path) as web:
        status, _, payload = request(web, "GET", "/api/v1/agent/codex")
        assert status == 200
        assert json.loads(payload)["connected"] is False

        status, _, payload = post(web, "/api/v1/agent/codex/connect", {"allow_actions": ["tasks", "study"]})
        assert status == 200
        connected = json.loads(payload)
        assert connected["connected"] is True
        assert connected["allow_actions"] == ["tasks", "study"]
        assert (codex_home / "config.toml").is_file()

        status, _, payload = post(web, "/api/v1/agent/codex/disconnect", {})
        assert status == 200
        assert json.loads(payload)["connected"] is False

        status, _, payload = post(web, "/api/v1/agent/codex/connect", {"allow_actions": ["unknown"]})
        assert status == 400
