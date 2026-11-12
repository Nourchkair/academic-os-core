"""Local MCP connection metadata and read-only tool grants.

Connection metadata lives in the runtime directory, never in the academic
workspace, profile.json, or workflow preferences. No credential is stored here.
External MCP servers start only for an explicit inspect/grant operation, and only
tools the server marks read-only can be granted.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

from .state import JsonStateStore
from .mcp_remote import KeychainTokenStore, OAuthSession, RemoteMCPError, remote_call, remote_inspect

SCHEMA_VERSION = 1
INSPECT_TIMEOUT_SECONDS = 20.0
MAX_ARGS = 40
MAX_ARG_LENGTH = 1000
MAX_NAME_LENGTH = 120
MAX_COMMAND_LENGTH = 1000
MAX_DESCRIPTION_LENGTH = 500
MAX_TOOLS = 200


class MCPConnectionError(ValueError):
    """A connection record is invalid or an operation is not safe."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise MCPConnectionError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _remote_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > 2000:
        raise MCPConnectionError("url must be a valid remote MCP endpoint")
    parts = urlsplit(value.strip())
    if parts.username or parts.password or parts.fragment:
        raise MCPConnectionError("url must not include credentials or a fragment")
    if parts.scheme == "https" and parts.hostname:
        return value.strip()
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip()
    raise MCPConnectionError("remote MCP endpoints must use HTTPS; HTTP is allowed only on loopback for local testing")


def _normalize_tool(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        return None
    annotations = value.get("annotations") if isinstance(value.get("annotations"), dict) else {}
    description = value.get("description")
    return {
        "name": name.strip(),
        "description": description[:MAX_DESCRIPTION_LENGTH] if isinstance(description, str) else "",
        "read_only": annotations.get("readOnlyHint") is True if annotations else value.get("read_only") is True,
        "destructive": annotations.get("destructiveHint") is True if annotations else value.get("destructive") is True,
        "open_world": annotations.get("openWorldHint") is True if annotations else value.get("open_world") is True,
    }


def _validate_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MCPConnectionError("MCP connection records must be objects")
    connection_id = _text(value.get("id"), "connection id", maximum=80)
    name = _text(value.get("name"), "name", maximum=MAX_NAME_LENGTH)
    transport = value.get("transport", "stdio")
    if transport not in {"stdio", "http"}:
        raise MCPConnectionError("only local stdio and remote HTTP MCP connections are supported")
    scope = value.get("scope", "read_only")
    if scope != "read_only":
        raise MCPConnectionError("only the read-only MCP scope is supported")
    trust = value.get("trust", "local")
    if trust not in {"local", "remote_unverified", "remote_trusted"}:
        raise MCPConnectionError("MCP connection trust level is invalid")
    if transport == "stdio" and trust != "local":
        raise MCPConnectionError("local stdio connections must use local trust")
    if transport == "http" and trust == "local":
        raise MCPConnectionError("remote connections require a remote trust level")
    if transport == "stdio":
        command = _text(value.get("command"), "command", maximum=MAX_COMMAND_LENGTH)
        url = None
    else:
        command = None
        url = _remote_url(value.get("url"))
    args = value.get("args", [])
    if not isinstance(args, list) or len(args) > MAX_ARGS or any(not isinstance(arg, str) or len(arg) > MAX_ARG_LENGTH or "\x00" in arg for arg in args):
        raise MCPConnectionError("args must be a bounded list of strings")
    if transport == "http" and args:
        raise MCPConnectionError("remote HTTP connections do not accept command arguments")
    cwd = value.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or not cwd.strip() or "\x00" in cwd):
        raise MCPConnectionError("cwd must be a local directory path or null")
    if transport == "http" and cwd is not None:
        raise MCPConnectionError("remote HTTP connections do not accept a working directory")
    auth_value = value.get("auth") if isinstance(value.get("auth"), dict) else {"type": "none"}
    auth_type = auth_value.get("type", "none")
    if auth_type not in {"none", "oauth"}:
        raise MCPConnectionError("MCP auth type is invalid")
    auth: dict[str, Any] = {"type": auth_type}
    if auth_type == "oauth":
        for field in ("authorization_server", "token_endpoint", "client_id", "redirect_uri"):
            raw = auth_value.get(field)
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
                raise MCPConnectionError(f"OAuth {field} is required")
            auth[field] = raw.strip()
        scopes = auth_value.get("scopes", [])
        if not isinstance(scopes, list) or any(not isinstance(item, str) or len(item) > 200 for item in scopes):
            raise MCPConnectionError("OAuth scopes must be a list of strings")
        auth["scopes"] = list(scopes)
    auth_status = value.get("auth_status", "none")
    if auth_status not in {"none", "pending", "authorized", "error"}:
        raise MCPConnectionError("MCP auth status is invalid")
    status = value.get("status", "unchecked")
    if status not in {"unchecked", "available", "error"}:
        raise MCPConnectionError("connection status is invalid")
    tools_value = value.get("tools", [])
    if not isinstance(tools_value, list):
        raise MCPConnectionError("tools must be a list")
    tools = [tool for tool in (_normalize_tool(item) for item in tools_value[:MAX_TOOLS]) if tool is not None]
    names = {tool["name"] for tool in tools}
    granted = value.get("granted_tools", [])
    if not isinstance(granted, list) or any(not isinstance(item, str) or item not in names for item in granted):
        raise MCPConnectionError("granted_tools must name inspected tools")
    read_only_names = {tool["name"] for tool in tools if tool["read_only"]}
    if any(item not in read_only_names for item in granted):
        raise MCPConnectionError("only read-only tools can be granted")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise MCPConnectionError("enabled must be true or false")
    server_info = value.get("server_info") if isinstance(value.get("server_info"), dict) else None
    if server_info is not None:
        server_info = {
            "name": server_info.get("name") if isinstance(server_info.get("name"), str) else None,
            "version": server_info.get("version") if isinstance(server_info.get("version"), str) else None,
        }
    return {
        "id": connection_id,
        "name": name,
        "transport": transport,
        "scope": "read_only",
        "trust": trust,
        "command": command,
        "url": url,
        "args": list(args),
        "cwd": cwd,
        "auth": auth,
        "auth_status": auth_status,
        "enabled": enabled and bool(granted),
        "status": status,
        "server_info": server_info,
        "tools": tools,
        "granted_tools": list(dict.fromkeys(granted)),
        "error": value.get("error") if isinstance(value.get("error"), str) else None,
        "created_at": _text(value.get("created_at"), "created_at", maximum=80),
        "updated_at": _text(value.get("updated_at"), "updated_at", maximum=80),
        "last_checked_at": value.get("last_checked_at") if isinstance(value.get("last_checked_at"), str) else None,
    }


class _MCPClient:
    def __init__(self, command: Sequence[str], *, cwd: str | None = None) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        self.process = subprocess.Popen(
            [str(part) for part in command],
            cwd=cwd or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._next_id = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._read_stdout, name="academia-external-mcp", daemon=True).start()

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
        with self._lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            self.process.stdin.flush()

    def read(self, timeout: float) -> dict[str, Any] | None:
        try:
            value = self._inbox.get(timeout=timeout)
        except queue.Empty:
            if self.process.poll() is not None:
                raise MCPConnectionError("external MCP server exited unexpectedly")
            return None
        if value is None:
            raise MCPConnectionError("external MCP server exited unexpectedly")
        if isinstance(value, Exception):
            raise MCPConnectionError(f"external MCP server returned invalid data: {value}")
        if not isinstance(value, dict):
            raise MCPConnectionError("external MCP server returned an invalid message")
        return value

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = INSPECT_TIMEOUT_SECONDS) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPConnectionError(f"external MCP request timed out: {method}")
            message = self.read(min(remaining, 0.5))
            if message is None:
                continue
            if message.get("id") == request_id:
                if isinstance(message.get("error"), dict):
                    raise MCPConnectionError(str(message["error"].get("message") or "external MCP request failed"))
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            if message.get("id") is not None and message.get("method"):
                self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": "Academia does not support this external MCP interaction"}})

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "academia-os-mcp-manager", "version": "0.1"},
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return result

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


def inspect_connection(record: dict[str, Any]) -> dict[str, Any]:
    command = [record["command"], *record["args"]]
    client: _MCPClient | None = None
    try:
        client = _MCPClient(command, cwd=record.get("cwd"))
        initialized = client.initialize()
        tools_result = client.request("tools/list", {})
        raw_tools = tools_result.get("tools") if isinstance(tools_result.get("tools"), list) else []
        tools = [tool for tool in (_normalize_tool(item) for item in raw_tools[:MAX_TOOLS]) if tool is not None]
        tools.sort(key=lambda tool: (not tool["read_only"], tool["name"].casefold()))
        server_info = initialized.get("serverInfo") if isinstance(initialized.get("serverInfo"), dict) else {}
        return {
            "status": "available",
            "server_info": {
                "name": server_info.get("name") if isinstance(server_info.get("name"), str) else None,
                "version": server_info.get("version") if isinstance(server_info.get("version"), str) else None,
            },
            "tools": tools,
            "error": None,
            "last_checked_at": _now(),
        }
    except (OSError, MCPConnectionError, subprocess.SubprocessError) as exc:
        return {
            "status": "error",
            "server_info": None,
            "tools": [],
            "error": str(exc),
            "last_checked_at": _now(),
        }
    finally:
        if client is not None:
            client.close()


class MCPConnectionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.store = JsonStateStore(self.path)

    @staticmethod
    def _default() -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "connections": []}

    def _read(self) -> dict[str, Any]:
        value = self.store.read_strict(self._default())
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("connections"), list):
            raise MCPConnectionError("MCP connection state has an unsupported structure")
        return {
            "schema_version": SCHEMA_VERSION,
            "connections": [_validate_record(item) for item in value["connections"]],
        }

    def list(self) -> list[dict[str, Any]]:
        return self._read()["connections"]

    def get(self, connection_id: str) -> dict[str, Any]:
        for item in self.list():
            if item["id"] == connection_id:
                return item
        raise KeyError(f"MCP connection not found: {connection_id}")

    def _update(self, transform: Any) -> dict[str, Any]:
        result_holder: dict[str, Any] = {}

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION or not isinstance(raw.get("connections"), list):
                raw = self._default()
            connections = [_validate_record(item) for item in raw["connections"]]
            connections, result = transform(connections)
            result_holder["value"] = result
            return {"schema_version": SCHEMA_VERSION, "connections": connections}

        self.store.update_strict(self._default(), transition)
        if "value" not in result_holder:
            raise MCPConnectionError("MCP connection state did not produce a result")
        return result_holder["value"]

    def add(self, *, name: str, command: str, args: Sequence[str] | None = None, cwd: str | None = None) -> dict[str, Any]:
        now = _now()
        record = _validate_record({
            "id": str(uuid4()),
            "name": name,
            "transport": "stdio",
            "scope": "read_only",
            "trust": "local",
            "command": command,
            "url": None,
            "args": list(args or []),
            "cwd": cwd,
            "auth": {"type": "none"},
            "auth_status": "none",
            "enabled": False,
            "status": "unchecked",
            "server_info": None,
            "tools": [],
            "granted_tools": [],
            "error": None,
            "created_at": now,
            "updated_at": now,
            "last_checked_at": None,
        })

        def transform(connections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            if any(item["name"].casefold() == record["name"].casefold() for item in connections):
                raise MCPConnectionError("an MCP connection with this name already exists")
            return [*connections, record], record

        return self._update(transform)

    def add_remote(self, *, name: str, url: str) -> dict[str, Any]:
        now = _now()
        record = _validate_record({
            "id": str(uuid4()),
            "name": name,
            "transport": "http",
            "scope": "read_only",
            "trust": "remote_unverified",
            "url": url,
            "command": None,
            "args": [],
            "cwd": None,
            "auth": {"type": "none"},
            "auth_status": "none",
            "enabled": False,
            "status": "unchecked",
            "server_info": None,
            "tools": [],
            "granted_tools": [],
            "error": None,
            "created_at": now,
            "updated_at": now,
            "last_checked_at": None,
        })

        def transform(connections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            if any(item["name"].casefold() == record["name"].casefold() for item in connections):
                raise MCPConnectionError("an MCP connection with this name already exists")
            return [*connections, record], record

        return self._update(transform)

    def update(self, connection_id: str, **fields: Any) -> dict[str, Any]:
        def transform(connections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            for index, item in enumerate(connections):
                if item["id"] != connection_id:
                    continue
                updated = _validate_record({**item, **fields, "id": item["id"], "created_at": item["created_at"], "updated_at": _now()})
                connections[index] = updated
                return connections, updated
            raise KeyError(f"MCP connection not found: {connection_id}")

        return self._update(transform)

    def remove(self, connection_id: str) -> dict[str, Any]:
        def transform(connections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            for item in connections:
                if item["id"] == connection_id:
                    return [entry for entry in connections if entry["id"] != connection_id], item
            raise KeyError(f"MCP connection not found: {connection_id}")

        return self._update(transform)


class MCPConnectionManager:
    def __init__(self, state_path: Path, *, token_store: KeychainTokenStore | None = None) -> None:
        self.store = MCPConnectionStore(state_path)
        self.token_store = token_store or KeychainTokenStore()
        self._oauth_sessions: dict[str, OAuthSession] = {}
        self._oauth_lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        return self.store.list()

    def add(self, *, name: str, command: str, args: Sequence[str] | None = None, cwd: str | None = None) -> dict[str, Any]:
        return self.store.add(name=name, command=command, args=args, cwd=cwd)

    def add_remote(self, *, name: str, url: str) -> dict[str, Any]:
        return self.store.add_remote(name=name, url=url)

    def inspect(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if record["transport"] == "http":
            if record["auth"]["type"] == "oauth" and record["auth_status"] != "authorized":
                raise MCPConnectionError("authorize the remote connection before inspecting it")
            result = remote_inspect(record, self.token_store)
        else:
            result = inspect_connection(record)
        return self.store.update(
            connection_id,
            status=result["status"],
            server_info=result["server_info"],
            tools=result["tools"],
            error=result["error"],
            last_checked_at=result["last_checked_at"],
            enabled=False if result["status"] != "available" else record["enabled"],
            granted_tools=[name for name in record["granted_tools"] if any(tool["name"] == name and tool["read_only"] for tool in result["tools"])],
        )

    def grant(self, connection_id: str, tools: Sequence[str]) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if record["status"] != "available":
            raise MCPConnectionError("inspect the connection before granting tools")
        if record["trust"] not in {"local", "remote_trusted"}:
            raise MCPConnectionError("trust the remote server's read-only declarations before granting tools")
        read_only = {tool["name"] for tool in record["tools"] if tool["read_only"]}
        requested = list(dict.fromkeys(str(tool) for tool in tools))
        if any(tool not in read_only for tool in requested):
            raise MCPConnectionError("only server-declared read-only tools can be granted")
        return self.store.update(
            connection_id,
            granted_tools=requested,
            enabled=bool(requested),
        )

    def call_read_tool(self, connection_id: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if not record["enabled"]:
            raise MCPConnectionError("enable the connection before calling a tool")
        if tool not in record["granted_tools"]:
            raise MCPConnectionError("tool is not granted for this connection")
        tool_record = next((item for item in record["tools"] if item["name"] == tool), None)
        if tool_record is None or not tool_record["read_only"]:
            raise MCPConnectionError("only granted read-only tools can be called")
        if record["transport"] == "http" and record["trust"] != "remote_trusted":
            raise MCPConnectionError("trust the remote server before calling its tools")
        if arguments is not None and not isinstance(arguments, dict):
            raise MCPConnectionError("arguments must be a JSON object")
        if record["transport"] == "http":
            try:
                return remote_call(record, tool, arguments or {}, self.token_store)
            except (OSError, RemoteMCPError) as exc:
                raise MCPConnectionError(str(exc)) from exc
        client: _MCPClient | None = None
        try:
            client = _MCPClient([record["command"], *record["args"]], cwd=record.get("cwd"))
            client.initialize()
            result = client.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout=INSPECT_TIMEOUT_SECONDS)
        except (OSError, MCPConnectionError, subprocess.SubprocessError) as exc:
            raise MCPConnectionError(str(exc)) from exc
        finally:
            if client is not None:
                client.close()
        content = result.get("content") if isinstance(result.get("content"), list) else []
        bounded: list[dict[str, Any]] = []
        total = 0
        for item in content[:20]:
            if not isinstance(item, dict):
                continue
            text = item.get("text") if isinstance(item.get("text"), str) else ""
            if not text:
                continue
            if total + len(text) > 64_000:
                text = text[:max(0, 64_000 - total)]
            bounded.append({"type": str(item.get("type") or "text"), "text": text})
            total += len(text)
            if total >= 64_000:
                break
        return {
            "connection_id": connection_id,
            "tool": tool,
            "is_error": bool(result.get("isError")),
            "content": bounded,
            "truncated": total >= 64_000,
        }

    def enable(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if record["status"] != "available":
            raise MCPConnectionError("inspect the connection before enabling it")
        if record["transport"] == "http" and record["trust"] != "remote_trusted":
            raise MCPConnectionError("trust the remote server before enabling its tools")
        if not record["granted_tools"]:
            raise MCPConnectionError("grant at least one read-only tool before enabling the connection")
        return self.store.update(connection_id, enabled=True)

    def trust_remote(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if record["transport"] != "http":
            raise MCPConnectionError("only remote connections require a trust decision")
        if record["status"] != "available":
            raise MCPConnectionError("inspect the remote server's declared tools before trusting it")
        return self.store.update(connection_id, trust="remote_trusted")

    def begin_authorize(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        if record["transport"] != "http":
            raise MCPConnectionError("only remote connections use OAuth")
        with self._oauth_lock:
            existing = self._oauth_sessions.get(connection_id)
            if existing is not None and existing.status == "pending":
                return {
                    "connection_id": connection_id,
                    "authorization_url": existing.authorization_url,
                    "state": existing.state,
                    "redirect_uri": existing.redirect_uri,
                    "auth_status": "pending",
                }
            session = OAuthSession(connection_id=connection_id, resource_url=str(record["url"]), store=self.token_store)

            def completed(auth: dict[str, Any]) -> None:
                try:
                    self.store.update(
                        connection_id,
                        auth=auth,
                        auth_status="authorized",
                        status="unchecked",
                        error=None,
                        enabled=False,
                    )
                except KeyError:
                    self.token_store.delete(connection_id)
                    raise

            try:
                value = session.begin(on_complete=completed)
            except (RemoteMCPError, OSError, ValueError) as exc:
                self.store.update(connection_id, auth_status="error", error=str(exc))
                raise MCPConnectionError(str(exc)) from exc
            auth = session.endpoints.as_auth_record(
                client_id=session.client_id,
                redirect_uri=session.redirect_uri,
                scopes=session.scopes,
            ) if session.endpoints is not None else {"type": "none"}
            updated = self.store.update(
                connection_id,
                auth=auth,
                auth_status="pending",
                status="unchecked",
                error=None,
                enabled=False,
            )
            self._oauth_sessions[connection_id] = session
            return {**value, "auth_status": "pending", "connection": updated}

    def oauth_status(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        with self._oauth_lock:
            session = self._oauth_sessions.get(connection_id)
        if session is None:
            return {"connection_id": connection_id, "auth_status": record["auth_status"], "error": record["error"], "connection": record}
        if session.status == "authorized":
            record = self.store.get(connection_id)
        elif session.status == "error":
            record = self.store.update(connection_id, auth_status="error", error=session.error or "OAuth authorization failed")
        elif session.status == "cancelled":
            record = self.store.update(connection_id, auth_status="none", error="Sign-in was cancelled.", enabled=False)
        return {
            "connection_id": connection_id,
            "auth_status": record["auth_status"],
            "error": record["error"],
            "session_status": session.status,
            "connection": record,
        }

    def cancel_authorize(self, connection_id: str) -> dict[str, Any]:
        record = self.store.get(connection_id)
        with self._oauth_lock:
            session = self._oauth_sessions.pop(connection_id, None)
        if record["auth_status"] == "authorized" or (session is not None and session.status == "authorized"):
            raise MCPConnectionError("OAuth authorization already completed; disconnect the connection to remove its tokens")
        if session is not None:
            session.cancel()
        record = self.store.update(connection_id, auth_status="none", error="Sign-in was cancelled.", enabled=False)
        return {**self.oauth_status(connection_id), "connection": record}

    def disconnect(self, connection_id: str) -> dict[str, Any]:
        self.token_store.delete(connection_id)
        return self.store.remove(connection_id)

    def disable(self, connection_id: str) -> dict[str, Any]:
        return self.store.update(connection_id, enabled=False)
