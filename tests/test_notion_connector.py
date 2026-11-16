from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from academia_os.connectors import notion


class MemoryNotionStore:
    def __init__(self) -> None:
        self.token: str | None = None

    def save(self, token: str) -> None:
        self.token = token

    def load(self) -> str | None:
        return self.token

    def delete(self) -> None:
        self.token = None


class FakeNotionServer:
    def __init__(self) -> None:
        self.requests: list[str] = []
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

            def _authorized(self) -> bool:
                return self.headers.get("Authorization") == "Bearer notion-token"

            def do_GET(self) -> None:
                owner.requests.append(self.path)
                if not self._authorized():
                    self._json(401, {"object": "error", "message": "unauthorized"})
                    return
                if self.path == "/v1/users/me":
                    self._json(200, {"object": "user", "name": "Student Workspace", "bot": {"owner": {"type": "workspace"}}})
                elif self.path.startswith("/v1/blocks/page-1/children"):
                    self._json(200, {"object": "list", "results": [
                        {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Week 4"}]}},
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Read the chapter."}]}},
                    ]})
                else:
                    self._json(404, {"object": "error", "message": "not found"})

            def do_POST(self) -> None:
                owner.requests.append(self.path)
                if not self._authorized():
                    self._json(401, {"object": "error", "message": "unauthorized"})
                    return
                if self.path == "/v1/search":
                    self._json(200, {"object": "list", "results": [{
                        "object": "page",
                        "id": "page-1",
                        "url": "https://notion.example/page-1",
                        "last_edited_time": "2026-11-12T10:00:00Z",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "POL 2103 Notes"}]}},
                    }]})
                else:
                    self._json(404, {"object": "error", "message": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def test_notion_connect_search_read_and_disconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeNotionServer()
    store = MemoryNotionStore()
    monkeypatch.setattr(notion, "NOTION_API", server.origin + "/v1")
    connector = notion.NotionConnector(tmp_path / "notion_connector.json", store=store)  # type: ignore[arg-type]
    try:
        status = connector.configure("notion-token")
        assert status["auth_status"] == "connected"
        assert status["account_name"] == "Student Workspace"
        assert store.token == "notion-token"
        assert "notion-token" not in (tmp_path / "notion_connector.json").read_text(encoding="utf-8")

        search = connector.search(query="POL", page_size=5)
        assert search["count"] == 1
        assert search["pages"][0]["title"] == "POL 2103 Notes"

        page = connector.read_page("page-1")
        assert "Week 4" in page["text"]
        assert "Read the chapter." in page["text"]

        disconnected = connector.disconnect()
        assert disconnected["auth_status"] == "not_configured"
        assert store.token is None
    finally:
        server.close()


def test_notion_rejects_bad_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeNotionServer()
    store = MemoryNotionStore()
    monkeypatch.setattr(notion, "NOTION_API", server.origin + "/v1")
    connector = notion.NotionConnector(tmp_path / "notion_connector.json", store=store)  # type: ignore[arg-type]
    try:
        with pytest.raises(notion.NotionConnectorError, match="rejected"):
            connector.configure("bad-token")
        assert store.token is None
        assert connector.status()["auth_status"] == "not_configured"
    finally:
        server.close()
