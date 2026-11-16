"""Remote streamable-HTTP MCP transport, OAuth device browser flow, and Keychain tokens.

Only the OAuth authorization code + PKCE flow is implemented. Tokens are stored
in the operating system credential store through ``keyring`` (macOS Keychain);
connection records never contain access or refresh tokens.
"""
from __future__ import annotations

import base64
import hashlib
import json
import queue
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping

MAX_RESPONSE_BYTES = 512 * 1024
OAUTH_TIMEOUT_SECONDS = 180.0
TOKEN_REFRESH_MARGIN_SECONDS = 60.0
KEYCHAIN_SERVICE = "academia-os-mcp-oauth"


class RemoteMCPError(ValueError):
    """A remote MCP or OAuth operation failed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000 or "\x00" in value:
        raise RemoteMCPError("remote URL is invalid")
    parts = urllib.parse.urlsplit(value.strip())
    if parts.username or parts.password or parts.fragment:
        raise RemoteMCPError("remote URL must not include credentials or a fragment")
    if parts.scheme == "https" and parts.hostname:
        return value.strip()
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip()
    raise RemoteMCPError("remote URLs must use HTTPS; HTTP is allowed only on loopback")


def _origin(value: str) -> str:
    parts = urllib.parse.urlsplit(_safe_url(value))
    return f"{parts.scheme}://{parts.netloc}"


def _http(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(_safe_url(url), data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise RemoteMCPError("remote server response exceeded the local limit")
            return response.status, {key.lower(): value for key, value in response.headers.items()}, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RemoteMCPError("remote server error response exceeded the local limit") from exc
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, payload
    except (OSError, urllib.error.URLError) as exc:
        raise RemoteMCPError(f"remote server could not be reached: {exc}") from exc


def _json_payload(method: str, url: str, value: Mapping[str, Any] | None = None, *, timeout: float = 20.0) -> dict[str, Any]:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8") if value is not None else None
    status, headers, payload = _http(
        method,
        url,
        body=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"} if body is not None else {"Accept": "application/json"},
        timeout=timeout,
    )
    if status < 200 or status >= 300:
        raise RemoteMCPError(f"remote server returned HTTP {status}")
    try:
        decoded = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteMCPError("remote server returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RemoteMCPError("remote server returned an unexpected JSON shape")
    return decoded


@dataclass(frozen=True)
class OAuthEndpoints:
    authorization_server: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scopes_supported: tuple[str, ...]

    def as_auth_record(self, *, client_id: str, redirect_uri: str, scopes: list[str]) -> dict[str, Any]:
        return {
            "type": "oauth",
            "authorization_server": self.authorization_server,
            "token_endpoint": self.token_endpoint,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
        }


def _discovery_document(base: str, suffix: str) -> dict[str, Any] | None:
    try:
        return _json_payload("GET", base.rstrip("/") + suffix)
    except RemoteMCPError:
        return None


def discover_oauth(resource_url: str) -> OAuthEndpoints:
    origin = _origin(resource_url)
    resource = _discovery_document(origin, "/.well-known/oauth-protected-resource")
    if resource is None:
        resource = _discovery_document(resource_url, "/.well-known/oauth-protected-resource")
    if not resource:
        raise RemoteMCPError("this server does not publish OAuth protected-resource metadata")
    servers = resource.get("authorization_servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
        raise RemoteMCPError("OAuth metadata did not identify an authorization server")
    auth_server = _origin(servers[0])
    metadata = _discovery_document(auth_server, "/.well-known/oauth-authorization-server")
    if not metadata:
        raise RemoteMCPError("the OAuth authorization server metadata could not be read")
    authorization_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    if not isinstance(authorization_endpoint, str) or not isinstance(token_endpoint, str):
        raise RemoteMCPError("OAuth metadata is missing its authorization or token endpoint")
    registration = metadata.get("registration_endpoint")
    scopes = resource.get("scopes_supported") if isinstance(resource.get("scopes_supported"), list) else []
    normalized_scopes = tuple(item for item in scopes if isinstance(item, str) and item)[:50]
    return OAuthEndpoints(
        authorization_server=auth_server,
        authorization_endpoint=_safe_url(authorization_endpoint),
        token_endpoint=_safe_url(token_endpoint),
        registration_endpoint=_safe_url(registration) if isinstance(registration, str) else None,
        scopes_supported=normalized_scopes,
    )


def register_client(endpoints: OAuthEndpoints, redirect_uri: str, scopes: list[str]) -> str:
    if endpoints.registration_endpoint is None:
        raise RemoteMCPError("this OAuth server requires a pre-registered client; dynamic registration is unavailable")
    value = _json_payload("POST", endpoints.registration_endpoint, {
        "client_name": "Academia OS",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(scopes),
    })
    client_id = value.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise RemoteMCPError("OAuth dynamic registration did not return a client id")
    if value.get("client_secret"):
        raise RemoteMCPError("confidential OAuth clients are not supported; configure a public client")
    return client_id


class KeychainTokenStore:
    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    def _account(self, connection_id: str) -> str:
        return f"connection:{connection_id}"

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise RemoteMCPError("macOS Keychain support requires the keyring package") from exc
        return keyring

    def save(self, connection_id: str, tokens: Mapping[str, Any]) -> None:
        safe = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "token_type": tokens.get("token_type") or "Bearer",
            "scope": tokens.get("scope"),
            "expires_at": tokens.get("expires_at"),
        }
        if not isinstance(safe["access_token"], str) or not safe["access_token"]:
            raise RemoteMCPError("OAuth token response did not include an access token")
        try:
            self._keyring().set_password(self.service, self._account(connection_id), json.dumps(safe, separators=(",", ":")))
        except Exception as exc:
            raise RemoteMCPError(f"OAuth tokens could not be saved to the system credential store: {exc}") from exc

    def load(self, connection_id: str) -> dict[str, Any] | None:
        try:
            raw = self._keyring().get_password(self.service, self._account(connection_id))
        except Exception as exc:
            raise RemoteMCPError(f"OAuth tokens could not be read from the system credential store: {exc}") from exc
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RemoteMCPError("stored OAuth token data is invalid") from exc
        if not isinstance(value, dict) or not isinstance(value.get("access_token"), str):
            raise RemoteMCPError("stored OAuth token data is invalid")
        return value

    def delete(self, connection_id: str) -> None:
        try:
            self._keyring().delete_password(self.service, self._account(connection_id))
        except Exception:
            return


def _form(url: str, values: Mapping[str, str], *, timeout: float = 20.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(values).encode("utf-8")
    status, _headers, payload = _http(
        "POST",
        url,
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=timeout,
    )
    if status < 200 or status >= 300:
        raise RemoteMCPError(f"OAuth token endpoint returned HTTP {status}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteMCPError("OAuth token endpoint returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RemoteMCPError("OAuth token endpoint returned an unexpected response")
    return value


def _token_bundle(value: Mapping[str, Any], fallback_refresh: str | None = None) -> dict[str, Any]:
    access = value.get("access_token")
    if not isinstance(access, str) or not access:
        raise RemoteMCPError("OAuth token response did not include an access token")
    expires_in = value.get("expires_in")
    expires_at = time.time() + expires_in if isinstance(expires_in, (int, float)) and expires_in > 0 else None
    refresh = value.get("refresh_token") if isinstance(value.get("refresh_token"), str) else fallback_refresh
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": value.get("token_type") if isinstance(value.get("token_type"), str) else "Bearer",
        "scope": value.get("scope") if isinstance(value.get("scope"), str) else None,
        "expires_at": expires_at,
    }


def refresh_tokens(record: Mapping[str, Any], store: KeychainTokenStore) -> dict[str, Any]:
    auth = record.get("auth") if isinstance(record.get("auth"), dict) else {}
    token_endpoint = auth.get("token_endpoint")
    client_id = auth.get("client_id")
    if not isinstance(token_endpoint, str) or not isinstance(client_id, str):
        raise RemoteMCPError("remote connection is missing OAuth metadata")
    connection_id = str(record.get("id"))
    current = store.load(connection_id)
    if current is None:
        raise RemoteMCPError("remote connection is not authorized")
    if current.get("access_token") and isinstance(current.get("expires_at"), (int, float)) and current["expires_at"] > time.time() + TOKEN_REFRESH_MARGIN_SECONDS:
        return current
    refresh = current.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise RemoteMCPError("OAuth authorization expired; sign in again")
    value = _form(token_endpoint, {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    })
    bundle = _token_bundle(value, fallback_refresh=refresh)
    store.save(connection_id, bundle)
    return bundle


def access_token(record: Mapping[str, Any], store: KeychainTokenStore) -> str | None:
    if record.get("transport") == "stdio":
        return None
    auth = record.get("auth") if isinstance(record.get("auth"), dict) else {}
    if auth.get("type") != "oauth":
        return None
    return refresh_tokens(record, store)["access_token"]


class RemoteMCPClient:
    def __init__(self, url: str, *, token: str | None = None, timeout: float = 20.0) -> None:
        self.url = _safe_url(url)
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2024-11-05",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _decode(self, status: int, headers: Mapping[str, str], payload: bytes, request_id: int) -> dict[str, Any]:
        if status < 200 or status >= 300:
            raise RemoteMCPError(f"remote MCP server returned HTTP {status}")
        session = headers.get("mcp-session-id")
        if isinstance(session, str) and session:
            self.session_id = session
        content_type = headers.get("content-type", "").casefold()
        if "text/event-stream" in content_type:
            for line in payload.decode("utf-8", errors="replace").splitlines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("id") == request_id:
                    if isinstance(value.get("error"), dict):
                        raise RemoteMCPError(str(value["error"].get("message") or "remote MCP request failed"))
                    result = value.get("result")
                    return result if isinstance(result, dict) else {}
            raise RemoteMCPError("remote MCP stream ended without a matching response")
        if payload:
            try:
                value = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RemoteMCPError("remote MCP server returned invalid JSON") from exc
            if isinstance(value, dict):
                if isinstance(value.get("error"), dict):
                    raise RemoteMCPError(str(value["error"].get("message") or "remote MCP request failed"))
                result = value.get("result")
                return result if isinstance(result, dict) else {}
        return {}

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, notification: bool = False) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": dict(params or {})}
        if not notification:
            message["id"] = request_id
        status, headers, payload = _http(
            "POST",
            self.url,
            body=json.dumps(message, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            timeout=self.timeout,
        )
        if notification:
            if status >= 300:
                raise RemoteMCPError(f"remote MCP server returned HTTP {status}")
            return {}
        return self._decode(status, headers, payload, request_id)

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "academia-os", "version": "0.1"},
        })
        self.request("notifications/initialized", notification=True)
        return result


def remote_inspect(record: Mapping[str, Any], store: KeychainTokenStore) -> dict[str, Any]:
    try:
        token = access_token(record, store)
        client = RemoteMCPClient(str(record["url"]), token=token)
        initialized = client.initialize()
        tools_result = client.request("tools/list", {})
        raw_tools = tools_result.get("tools") if isinstance(tools_result.get("tools"), list) else []
        tools = []
        for item in raw_tools[:200]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
            tools.append({
                "name": item["name"][:200],
                "description": item.get("description")[:500] if isinstance(item.get("description"), str) else "",
                "read_only": annotations.get("readOnlyHint") is True,
                "destructive": annotations.get("destructiveHint") is True,
                "open_world": annotations.get("openWorldHint") is True,
            })
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
    except (OSError, RemoteMCPError) as exc:
        return {"status": "error", "server_info": None, "tools": [], "error": str(exc), "last_checked_at": _now()}


def remote_call(record: Mapping[str, Any], tool: str, arguments: Mapping[str, Any], store: KeychainTokenStore) -> dict[str, Any]:
    token = access_token(record, store)
    client = RemoteMCPClient(str(record["url"]), token=token)
    client.initialize()
    result = client.request("tools/call", {"name": tool, "arguments": dict(arguments)})
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
        "connection_id": record.get("id"),
        "tool": tool,
        "is_error": bool(result.get("isError")),
        "content": bounded,
        "truncated": total >= 64_000,
    }


class OAuthSession:
    def __init__(self, *, connection_id: str, resource_url: str, store: KeychainTokenStore, timeout: float = OAUTH_TIMEOUT_SECONDS) -> None:
        self.connection_id = connection_id
        self.resource_url = resource_url
        self.store = store
        self.timeout = timeout
        self.endpoints: OAuthEndpoints | None = None
        self.authorization_url = ""
        self.state = ""
        self.redirect_uri = ""
        self.client_id = ""
        self.scopes: list[str] = []
        self.status = "pending"
        self.error: str | None = None
        self.auth_record: dict[str, Any] | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[tuple[str | None, str | None]] = queue.Queue()
        self._cancelled = False
        self._verifier = ""
        self._on_complete: Callable[[dict[str, Any]], None] | None = None

    def _start_callback(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                if parts.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = urllib.parse.parse_qs(parts.query)
                code = query.get("code", [None])[0]
                state = query.get("state", [None])[0]
                error = query.get("error", [None])[0]
                if state != owner.state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"OAuth state did not match. Return to Academia OS.")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Academia OS sign-in complete</h1><p>You can close this window.</p></body></html>")
                self._owner._queue.put((code, error))

            @property
            def _owner(self) -> OAuthSession:
                return owner

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        self._server = server
        self.redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
        threading.Thread(target=server.serve_forever, name="academia-oauth-callback", daemon=True).start()

    def begin(self, *, on_complete: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        self.endpoints = discover_oauth(self.resource_url)
        scopes = list(self.endpoints.scopes_supported) or ["mcp.read"]
        self._start_callback()
        self.client_id = register_client(self.endpoints, self.redirect_uri, scopes)
        self.state = base64.urlsafe_b64encode(secrets.token_bytes(24)).decode("ascii").rstrip("=")
        self._verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        self.scopes = scopes
        query = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": self.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": self.resource_url,
        })
        self.authorization_url = f"{self.endpoints.authorization_endpoint}{'&' if '?' in self.endpoints.authorization_endpoint else '?'}{query}"
        self._on_complete = on_complete
        self._thread = threading.Thread(target=self._wait, name="academia-oauth-worker", daemon=True)
        self._thread.start()
        return {
            "connection_id": self.connection_id,
            "authorization_url": self.authorization_url,
            "state": self.state,
            "redirect_uri": self.redirect_uri,
            "expires_in": int(self.timeout),
        }

    def _wait(self) -> None:
        try:
            code, error = self._queue.get(timeout=self.timeout)
            if self._cancelled:
                return
            if error:
                raise RemoteMCPError(f"OAuth authorization failed: {error}")
            if not code:
                raise RemoteMCPError("OAuth callback did not include a code")
            assert self.endpoints is not None
            value = _form(self.endpoints.token_endpoint, {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": self._verifier,
            })
            bundle = _token_bundle(value)
            self.store.save(self.connection_id, bundle)
            self.auth_record = self.endpoints.as_auth_record(client_id=self.client_id, redirect_uri=self.redirect_uri, scopes=self.scopes)
            self.status = "authorized"
            if self._on_complete is not None:
                self._on_complete(self.auth_record)
        except (RemoteMCPError, OSError, queue.Empty, KeyError) as exc:
            if not self._cancelled:
                self.status = "error"
                self.error = "OAuth authorization timed out" if isinstance(exc, queue.Empty) else str(exc)
        finally:
            self.close_server()

    def cancel(self) -> None:
        self._cancelled = True
        self.status = "cancelled"
        self.close_server()

    def close_server(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
