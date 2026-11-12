"""Cross-process cancellation and NDJSON streams for the native desktop bridge.

The browser dashboard keeps chat and sign-in runs in the server process, so it can
cancel them in memory. The Tauri shell invokes the CLI for each action, which means
cancellation has to cross process boundaries. A run advertises a short-lived marker
under the runtime directory; a separate CLI command writes a cancel request file,
and the streaming process watches for it.

Only bounded, validated run identifiers are accepted. The files contain no academic
content or credentials and are removed when the run ends.
"""
from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .config import load_config, runtime_directory

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_CANCEL_POLL_SECONDS = 0.15


class NativeBridgeError(ValueError):
    """A native stream request was invalid or could not be started."""


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
        raise NativeBridgeError("run id must contain only letters, numbers, hyphens, or underscores")
    return value


def _run_directory(profile: Path, kind: str) -> Path:
    config = load_config(Path(profile).expanduser())
    root = runtime_directory(config) / "native_runs" / kind
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def run_lease(profile: Path, kind: str, run_id: str, on_cancel: Callable[[], None]):
    """Mark a run as active and invoke ``on_cancel`` once a cancel request appears."""
    run_id = _run_id(run_id)
    root = _run_directory(profile, kind)
    active = root / f"{run_id}.active"
    cancel = root / f"{run_id}.cancel"
    cancel.unlink(missing_ok=True)
    active.write_text(str(threading.get_ident()), encoding="utf-8")
    stopped = threading.Event()

    def watch() -> None:
        while not stopped.wait(_CANCEL_POLL_SECONDS):
            if cancel.exists():
                try:
                    on_cancel()
                finally:
                    return

    watcher = threading.Thread(target=watch, name=f"academia-{kind}-cancel", daemon=True)
    watcher.start()
    try:
        if cancel.exists():
            on_cancel()
        yield
    finally:
        stopped.set()
        watcher.join(timeout=1.0)
        active.unlink(missing_ok=True)
        cancel.unlink(missing_ok=True)


def request_cancel(profile: Path, kind: str, run_id: str) -> dict[str, Any]:
    """Ask an active native run to cancel and report whether it was active."""
    run_id = _run_id(run_id)
    if kind not in {"chat", "account", "mcp"}:
        raise NativeBridgeError("run kind is invalid")
    root = _run_directory(profile, kind)
    active = root / f"{run_id}.active"
    if not active.exists():
        return {"run_id": run_id, "cancelled": False}
    (root / f"{run_id}.cancel").write_text(str(time.time()), encoding="utf-8")
    return {"run_id": run_id, "cancelled": True}


def stream_chat(
    payload: Any,
    *,
    profile: Path,
    run_id: str,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    from .assistant.providers.base import CancelToken
    from .dashboard_chat import stream_chat as run_stream

    cancel = CancelToken()
    try:
        with run_lease(profile, "chat", run_id, cancel.cancel):
            run_stream(payload, profile=profile, run_id=run_id, cancel=cancel, emit=emit)
    except (OSError, ValueError) as exc:
        emit({"type": "error", "message": str(exc)})


def stream_account_login(
    *,
    profile: Path,
    run_id: str,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    from .assistant.account import LOGIN_TIMEOUT_SECONDS, CodexAccountManager

    manager = CodexAccountManager()
    try:
        with run_lease(profile, "account", run_id, manager.cancel_login):
            state = manager.start_login()
            deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS + 30.0
            sent_verification = False
            while True:
                if state["status"] == "awaiting_user" and not sent_verification:
                    emit({"type": "verification", "state": state})
                    sent_verification = True
                if state["status"] in {"signed_in", "signed_out", "failed", "cancelled", "unavailable"}:
                    break
                if time.monotonic() >= deadline:
                    state = manager.cancel_login()
                    state = {**state, "notice": "Codex sign-in timed out."}
                    break
                time.sleep(0.25)
                state = manager.status()
            emit({"type": "final", "state": state})
    except (OSError, ValueError) as exc:
        emit({"type": "error", "message": str(exc)})
    finally:
        manager.close()


def account_status(profile: Path) -> dict[str, Any]:
    from .assistant.account import CodexAccountManager

    manager = CodexAccountManager()
    try:
        return manager.status(refresh=True)
    finally:
        manager.close()


def account_logout(profile: Path) -> dict[str, Any]:
    from .assistant.account import CodexAccountManager

    manager = CodexAccountManager()
    try:
        return manager.logout()
    finally:
        manager.close()
