from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from academia_os import native_bridge
from academia_os.config import load_config, runtime_directory


def _profile(tmp_path: Path) -> Path:
    from tests.test_agent_interface import prepared_workspace

    _, _, profile = prepared_workspace(tmp_path / "workspace")
    return profile


def _wait_for_marker(profile: Path, kind: str, run_id: str) -> Path:
    root = runtime_directory(load_config(profile)) / "native_runs" / kind
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        marker = root / f"{run_id}.active"
        if marker.exists():
            return marker
        time.sleep(0.02)
    raise AssertionError("native run marker was not created")


def test_cancel_request_requires_an_active_run(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    result = native_bridge.request_cancel(profile, "chat", "run-one")
    assert result == {"run_id": "run-one", "cancelled": False}
    with pytest.raises(native_bridge.NativeBridgeError):
        native_bridge.request_cancel(profile, "chat", "../escape")


def test_run_lease_invokes_cancel_and_cleans_up(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    cancelled = threading.Event()
    with native_bridge.run_lease(profile, "chat", "run-two", cancelled.set):
        marker = _wait_for_marker(profile, "chat", "run-two")
        assert native_bridge.request_cancel(profile, "chat", "run-two")["cancelled"] is True
        assert cancelled.wait(timeout=3)
        assert marker.exists()
    assert not marker.exists()


def test_chat_stream_emits_events_and_cancel_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile(tmp_path)
    import academia_os.dashboard_chat as chat

    def fake_stream(payload, *, profile, run_id, cancel, emit):
        emit({"type": "started", "run_id": run_id})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if cancel.cancelled:
                emit({"type": "cancelled"})
                return
            time.sleep(0.02)
        emit({"type": "final", "message": "done"})

    monkeypatch.setattr(chat, "stream_chat", fake_stream)
    events = []
    worker = threading.Thread(target=native_bridge.stream_chat, args=({"messages": []},), kwargs={
        "profile": profile,
        "run_id": "run-three",
        "emit": events.append,
    })
    worker.start()
    _wait_for_marker(profile, "chat", "run-three")
    assert native_bridge.request_cancel(profile, "chat", "run-three")["cancelled"] is True
    worker.join(timeout=5)
    assert events == [
        {"type": "started", "run_id": "run-three"},
        {"type": "cancelled"},
    ]


def test_account_login_stream_emits_verification_and_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile(tmp_path)
    import academia_os.assistant.account as account

    class FakeManager:
        def __init__(self) -> None:
            self.state = {"status": "starting"}
            self.polls = 0

        def start_login(self):
            self.state = {"status": "awaiting_user", "user_code": "ABCD-EFGH", "verification_url": "https://example.test"}
            return dict(self.state)

        def status(self):
            self.polls += 1
            if self.polls >= 1:
                self.state = {"status": "signed_in", "authenticated": True}
            return dict(self.state)

        def cancel_login(self):
            self.state = {"status": "cancelled", "authenticated": False}
            return dict(self.state)

        def close(self):
            return None

    monkeypatch.setattr(account, "CodexAccountManager", FakeManager)
    events = []
    native_bridge.stream_account_login(profile=profile, run_id="login-one", emit=events.append)
    assert events[0]["type"] == "verification"
    assert events[0]["state"]["user_code"] == "ABCD-EFGH"
    assert events[-1]["type"] == "final"
    assert events[-1]["state"]["status"] == "signed_in"


def test_account_login_stream_cancels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile(tmp_path)
    import academia_os.assistant.account as account

    class SlowManager:
        def __init__(self) -> None:
            self.state = {"status": "starting"}

        def start_login(self):
            self.state = {"status": "awaiting_user", "user_code": "CODE", "verification_url": "https://example.test"}
            return dict(self.state)

        def status(self):
            return dict(self.state)

        def cancel_login(self):
            self.state = {"status": "cancelled", "authenticated": False}
            return dict(self.state)

        def close(self):
            return None

    monkeypatch.setattr(account, "CodexAccountManager", SlowManager)
    events = []
    worker = threading.Thread(target=native_bridge.stream_account_login, kwargs={
        "profile": profile,
        "run_id": "login-two",
        "emit": events.append,
    })
    worker.start()
    _wait_for_marker(profile, "account", "login-two")
    assert native_bridge.request_cancel(profile, "account", "login-two")["cancelled"] is True
    worker.join(timeout=5)
    assert events[0]["type"] == "verification"
    assert events[-1] == {"type": "final", "state": {"status": "cancelled", "authenticated": False}}


def test_cli_cancel_commands_are_safe_when_no_run_is_active(tmp_path: Path) -> None:
    from tests.test_agent_interface import prepared_workspace, run_cli

    _, _, profile = prepared_workspace(tmp_path / "workspace")
    chat = run_cli(profile, "chat-cancel", "--run-id", "missing-run", "--json")
    assert chat.returncode == 0, chat.stderr
    assert json.loads(chat.stdout) == {"run_id": "missing-run", "cancelled": False}
    account = run_cli(profile, "account", "login-cancel", "--run-id", "missing-run", "--json")
    assert account.returncode == 0, account.stderr
    assert json.loads(account.stdout) == {"run_id": "missing-run", "cancelled": False}
