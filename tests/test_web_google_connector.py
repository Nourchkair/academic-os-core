from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from academia_os.connectors.google import GoogleConnector
from tests.test_google_connector import FakeGoogleServer, MemoryGoogleStore, _configure
from tests.test_web import request, running_server


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_google_connector_web_routes(tmp_path: Path) -> None:
    remote = FakeGoogleServer()
    store = MemoryGoogleStore()
    try:
        with running_server(tmp_path) as web:
            web.google_connector = GoogleConnector(tmp_path / "runtime" / "google_connector.json", store=store)  # type: ignore[arg-type]
            _configure(web.google_connector, remote)

            status, _, payload = request(web, "GET", "/api/v1/connectors/google")
            assert status == 200
            assert json.loads(payload)["auth_status"] == "configured"
            assert json.loads(payload)["client_id"] == "client-id"

            status, _, payload = post(web, "/api/v1/connectors/google/authorize", {})
            assert status == 200
            started = json.loads(payload)
            assert started["auth_status"] == "pending"
            urllib.request.urlopen(started["authorization_url"], timeout=10).read()

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status, _, payload = post(web, "/api/v1/connectors/google/oauth-status", {})
                assert status == 200
                current = json.loads(payload)
                if current["auth_status"] in {"authorized", "error"}:
                    break
                time.sleep(0.05)
            assert current["auth_status"] == "authorized"
            assert current["connection"]["account_email"] == "student@example.edu"

            status, _, payload = post(web, "/api/v1/connectors/google/disconnect", {})
            assert status == 200
            assert json.loads(payload)["auth_status"] == "configured"
    finally:
        remote.close()


def test_google_connector_setup_rejects_missing_credentials(tmp_path: Path) -> None:
    with running_server(tmp_path) as web:
        status, _, payload = post(web, "/api/v1/connectors/google/setup", {"client_id": "", "client_secret": ""})
        assert status == 422
        assert json.loads(payload)["type"] == "GoogleConnectorError"


def test_google_connector_state_file_never_contains_the_secret(tmp_path: Path) -> None:
    store = MemoryGoogleStore()
    path = tmp_path / "runtime" / "google_connector.json"
    connector = GoogleConnector(path, store=store)  # type: ignore[arg-type]
    connector.configure(client_id="client-id", client_secret="super-secret")
    assert "super-secret" not in path.read_text(encoding="utf-8")
    assert store.client == {"client_id": "client-id", "client_secret": "super-secret"}
