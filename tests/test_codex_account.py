from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from academia_os.assistant.account import CodexAccountManager

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_codex_account_server.py"


def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "success") -> tuple[CodexAccountManager, Path]:
    marker = tmp_path / "signed-in.marker"
    monkeypatch.setenv("FAKE_ACCOUNT_MARKER", str(marker))
    monkeypatch.setenv("FAKE_ACCOUNT_MODE", mode)
    return CodexAccountManager(
        codex_command=(sys.executable, str(FAKE_SERVER)),
        timeout_seconds=5.0,
    ), marker


def wait_for(manager: CodexAccountManager, status: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = manager.status()
        if value["status"] == status:
            return value
        time.sleep(0.05)
    return manager.status()


def test_status_starts_signed_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account, _ = manager(tmp_path, monkeypatch)
    try:
        value = account.status(refresh=True)
        assert value["status"] == "signed_out"
        assert value["authenticated"] is False
        assert value["account"] is None
    finally:
        account.close()


def test_device_code_login_and_logout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account, marker = manager(tmp_path, monkeypatch)
    try:
        started = account.start_login()
        assert started["status"] in {"awaiting_user", "signed_in"}
        if started["status"] == "awaiting_user":
            assert started["verification_url"] == "https://example.test/device"
            assert started["user_code"] == "ABCD-EFGH"
        signed_in = wait_for(account, "signed_in")
        assert signed_in["authenticated"] is True
        assert signed_in["account"]["email"] == "student@example.edu"
        assert signed_in["account"]["plan_type"] == "plus"
        assert "access" not in json.dumps(signed_in).casefold()
        assert marker.exists()

        signed_out = account.logout()
        assert signed_out["status"] == "signed_out"
        assert signed_out["authenticated"] is False
        assert not marker.exists()
    finally:
        account.close()


def test_cancel_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account, _ = manager(tmp_path, monkeypatch, mode="cancel")
    try:
        started = account.start_login()
        assert started["status"] == "awaiting_user"
        cancelled = account.cancel_login()
        assert cancelled["status"] == "cancelled"
        assert cancelled["authenticated"] is False
    finally:
        account.close()
