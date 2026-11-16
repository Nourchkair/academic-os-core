from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.test_web import request, running_server


class FakeAccountManager:
    def __init__(self) -> None:
        self.value = {
            "provider": "codex",
            "available": True,
            "authenticated": False,
            "status": "signed_out",
            "account": None,
            "login_id": None,
            "verification_url": None,
            "user_code": None,
            "error": None,
            "notice": None,
            "updated_at": "2026-11-12T00:00:00Z",
        }
        self.actions: list[str] = []

    def status(self, **kwargs: Any) -> dict[str, Any]:
        return dict(self.value)

    def start_login(self) -> dict[str, Any]:
        self.actions.append("login")
        return {**self.value, "status": "awaiting_user", "login_id": "login-1", "verification_url": "https://example.test/device", "user_code": "ABCD-EFGH"}

    def cancel_login(self) -> dict[str, Any]:
        self.actions.append("cancel")
        return {**self.value, "status": "cancelled"}

    def logout(self) -> dict[str, Any]:
        self.actions.append("logout")
        return {**self.value, "status": "signed_out"}

    def close(self) -> None:
        self.actions.append("close")


def test_account_status_and_login_routes(tmp_path: Path) -> None:
    with running_server(tmp_path) as server:
        fake = FakeAccountManager()
        server.account_manager = fake
        status, _, payload = request(server, "GET", "/api/v1/account")
        assert status == 200
        assert json.loads(payload)["status"] == "signed_out"

        status, _, payload = request(server, "POST", "/api/v1/account/login")
        assert status == 200
        value = json.loads(payload)
        assert value["status"] == "awaiting_user"
        assert value["user_code"] == "ABCD-EFGH"

        status, _, payload = request(server, "POST", "/api/v1/account/login/cancel")
        assert status == 200
        assert json.loads(payload)["status"] == "cancelled"

        status, _, payload = request(server, "POST", "/api/v1/account/logout")
        assert status == 200
        assert json.loads(payload)["status"] == "signed_out"
        assert fake.actions == ["login", "cancel", "logout"]
