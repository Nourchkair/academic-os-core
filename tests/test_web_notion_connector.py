from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.connectors import notion
from tests.test_notion_connector import FakeNotionServer, MemoryNotionStore
from tests.test_web import request, running_server


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_notion_connector_web_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = FakeNotionServer()
    monkeypatch.setattr(notion, "NOTION_API", remote.origin + "/v1")
    try:
        with running_server(tmp_path) as web:
            web.notion_connector = notion.NotionConnector(tmp_path / "runtime" / "notion_connector.json", store=MemoryNotionStore())  # type: ignore[arg-type]

            status, _, payload = request(web, "GET", "/api/v1/connectors/notion")
            assert status == 200
            assert json.loads(payload)["auth_status"] == "not_configured"

            status, _, payload = post(web, "/api/v1/connectors/notion/setup", {"token": "notion-token"})
            assert status == 200
            assert json.loads(payload)["auth_status"] == "connected"

            status, _, payload = post(web, "/api/v1/connectors/notion/search", {"query": "POL", "max": 5})
            assert status == 200
            assert json.loads(payload)["pages"][0]["title"] == "POL 2103 Notes"

            status, _, payload = post(web, "/api/v1/connectors/notion/read", {"page_id": "page-1"})
            assert status == 200
            assert "Week 4" in json.loads(payload)["text"]

            status, _, payload = post(web, "/api/v1/connectors/notion/disconnect", {})
            assert status == 200
            assert json.loads(payload)["auth_status"] == "not_configured"
    finally:
        remote.close()
