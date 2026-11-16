"""App-level ChatGPT sign-in through the official Codex app-server.

Academia never reads, copies, or stores Codex credentials. The manager starts the
official device-code flow, exposes only the verification URL and one-time code,
and reads the signed-in account summary after Codex completes its own login.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

LOGIN_TIMEOUT_SECONDS = 300.0
STATUS_CACHE_SECONDS = 8.0
_SUBSCRIPTION_ENV_REMOVE = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "OPENAI_BASE_URL",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _AppServerClient:
    def __init__(self, command: Sequence[str], environment: dict[str, str]) -> None:
        self.process = subprocess.Popen(
            [str(part) for part in command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._next_id = 0
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_stdout, name="academia-codex-account", daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                if line.strip():
                    self._inbox.put(json.loads(line))
        except Exception as exc:
            self._inbox.put(exc)
        finally:
            self._inbox.put(None)

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        with self._write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            self.process.stdin.flush()

    def read(self, timeout: float) -> dict[str, Any] | None:
        try:
            value = self._inbox.get(timeout=timeout)
        except queue.Empty:
            if self.process.poll() is not None:
                raise RuntimeError("Codex app-server exited unexpectedly")
            return None
        if value is None:
            raise RuntimeError("Codex app-server exited unexpectedly")
        if isinstance(value, Exception):
            raise RuntimeError(f"Codex app-server returned invalid data: {value}")
        if not isinstance(value, dict):
            raise RuntimeError("Codex app-server returned an invalid message")
        return value

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"Codex account request timed out: {method}")
            message = self.read(min(remaining, 0.5))
            if message is None:
                continue
            if message.get("id") == request_id:
                if isinstance(message.get("error"), dict):
                    raise RuntimeError(str(message["error"].get("message") or "Codex account request failed"))
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if message.get("id") is not None and message.get("method"):
                self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": "Academia does not support this host interaction"}})

    def initialize(self) -> None:
        self.request("initialize", {"clientInfo": {"name": "academia-os-account", "version": "0.1"}, "capabilities": {}})
        self.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def close(self) -> None:
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if self.process.stdout is not None:
            self.process.stdout.close()


def _sanitize_account(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") != "chatgpt":
        return None
    return {
        "type": "chatgpt",
        "email": value.get("email") if isinstance(value.get("email"), str) else None,
        "plan_type": value.get("planType") if isinstance(value.get("planType"), str) else None,
        "workspace_name": value.get("workspaceName") if isinstance(value.get("workspaceName"), str) else None,
    }


class CodexAccountManager:
    def __init__(
        self,
        *,
        codex_command: Sequence[str] = ("codex", "app-server", "--stdio"),
        timeout_seconds: float = LOGIN_TIMEOUT_SECONDS,
    ) -> None:
        self._command = tuple(str(part) for part in codex_command)
        self._timeout = timeout_seconds
        self._lock = threading.RLock()
        self._read_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._client: _AppServerClient | None = None
        self._login_started = threading.Event()
        self._cancelled = False
        self._last_read = 0.0
        self._state: dict[str, Any] = {
            "provider": "codex",
            "available": self._available(),
            "authenticated": False,
            "status": "unknown",
            "account": None,
            "login_id": None,
            "verification_url": None,
            "user_code": None,
            "error": None,
            "notice": None,
            "updated_at": _now(),
        }

    def _available(self) -> bool:
        executable = self._command[0] if self._command else ""
        return bool(executable and (Path(executable).is_file() or shutil.which(executable)))

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        for key in _SUBSCRIPTION_ENV_REMOVE:
            environment.pop(key, None)
        return environment

    def _set(self, **values: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(values)
            self._state["updated_at"] = _now()
            return dict(self._state)

    def _signed_out_state(self, *, status: str = "signed_out", notice: str | None = None) -> dict[str, Any]:
        return self._set(
            authenticated=False,
            status=status,
            account=None,
            login_id=None,
            verification_url=None,
            user_code=None,
            error=None,
            notice=notice,
        )

    def _read_account_once(self) -> dict[str, Any] | None:
        client = _AppServerClient(self._command, self._environment())
        try:
            client.initialize()
            result = client.request("account/read", {"refreshToken": False}, timeout=20.0)
            return _sanitize_account(result.get("account"))
        finally:
            client.close()

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            worker_alive = self._worker is not None and self._worker.is_alive()
            state = dict(self._state)
            last_read = self._last_read
        if worker_alive:
            return state
        if not state["available"]:
            return self._set(status="unavailable", authenticated=False, account=None, error=None, notice="Codex CLI is unavailable.")
        if not refresh and state["status"] in {"signed_in", "signed_out", "failed"} and time.monotonic() - last_read < STATUS_CACHE_SECONDS:
            return state
        try:
            with self._read_lock:
                account = self._read_account_once()
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return self._set(status="failed", authenticated=False, account=None, error=str(exc), notice=None)
        self._last_read = time.monotonic()
        if account is not None:
            return self._set(authenticated=True, status="signed_in", account=account, login_id=None, verification_url=None, user_code=None, error=None, notice=None)
        return self._signed_out_state(notice="Sign in to Codex with ChatGPT. Academia does not use API billing.")

    def start_login(self) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return dict(self._state)
            if not self._available():
                return self._set(status="unavailable", authenticated=False, error=None, notice="Codex CLI is unavailable.")
            self._cancelled = False
            self._login_started.clear()
            self._set(status="starting", authenticated=False, account=None, login_id=None, verification_url=None, user_code=None, error=None, notice=None)
            self._worker = threading.Thread(target=self._login_worker, name="academia-codex-login", daemon=True)
            self._worker.start()
        self._login_started.wait(timeout=20.0)
        with self._lock:
            return dict(self._state)

    def _login_worker(self) -> None:
        client: _AppServerClient | None = None
        success = False
        try:
            client = _AppServerClient(self._command, self._environment())
            with self._lock:
                self._client = client
            client.initialize()
            response = client.request("account/login/start", {"type": "chatgptDeviceCode"}, timeout=30.0)
            login_type = response.get("type")
            if login_type != "chatgptDeviceCode":
                raise RuntimeError("Codex did not start a device-code login")
            login_id = response.get("loginId")
            user_code = response.get("userCode")
            verification_url = response.get("verificationUrl")
            if not all(isinstance(value, str) and value for value in (login_id, user_code, verification_url)):
                raise RuntimeError("Codex returned an incomplete device-code login")
            self._set(
                status="awaiting_user",
                authenticated=False,
                login_id=login_id,
                verification_url=verification_url,
                user_code=user_code,
                error=None,
                notice="Open the verification page and enter the one-time code.",
            )
            self._login_started.set()
            deadline = time.monotonic() + self._timeout
            while not self._cancelled and time.monotonic() < deadline:
                message = client.read(0.5)
                if message is None:
                    continue
                if message.get("id") is not None and message.get("method"):
                    client.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": "Academia does not support this host interaction"}})
                    continue
                if message.get("method") != "account/login/completed":
                    continue
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                if params.get("success") is True:
                    success = True
                    break
                error = params.get("error")
                raise RuntimeError(str(error) if error else "Codex sign-in did not complete")
            if not success and not self._cancelled:
                raise RuntimeError("Codex sign-in timed out")
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            if not self._cancelled:
                self._set(status="failed", authenticated=False, error=str(exc), notice=None)
        finally:
            self._login_started.set()
            if client is not None:
                client.close()
            with self._lock:
                self._client = None
        if success:
            try:
                with self._read_lock:
                    account = self._read_account_once()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                self._set(status="signed_in", authenticated=True, account=None, error=str(exc), notice="Signed in, but the account summary could not be read.")
            else:
                if account is not None:
                    self._last_read = time.monotonic()
                    self._set(authenticated=True, status="signed_in", account=account, login_id=None, verification_url=None, user_code=None, error=None, notice=None)
                else:
                    self._set(authenticated=True, status="signed_in", account=None, login_id=None, verification_url=None, user_code=None, error=None, notice=None)

    def cancel_login(self) -> dict[str, Any]:
        with self._lock:
            worker = self._worker
            if worker is None or not worker.is_alive():
                active = False
            else:
                active = True
                self._cancelled = True
                client = self._client
        if not active:
            return self.status(refresh=True)
        if client is not None:
            client.close()
        worker.join(timeout=3.0)
        return self._set(
            status="cancelled",
            authenticated=False,
            account=None,
            login_id=None,
            verification_url=None,
            user_code=None,
            error=None,
            notice="Sign-in was cancelled.",
        )

    def logout(self) -> dict[str, Any]:
        self.cancel_login()
        try:
            client = _AppServerClient(self._command, self._environment())
            try:
                client.initialize()
                client.request("account/logout", {}, timeout=20.0)
            finally:
                client.close()
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return self._set(status="failed", authenticated=False, error=str(exc), notice=None)
        self._last_read = time.monotonic()
        return self._signed_out_state(notice="Signed out of Codex on this device.")

    def close(self) -> None:
        with self._lock:
            self._cancelled = True
            client = self._client
        if client is not None:
            client.close()
