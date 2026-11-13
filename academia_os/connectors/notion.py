"""Read-only Notion app connection using an internal integration token."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
KEYCHAIN_SERVICE = "academia-os-notion"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class NotionConnectorError(ValueError):
    """A Notion operation failed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if parts.scheme == "https" and parts.hostname:
        return value
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value
    raise NotionConnectorError("Notion endpoints must use HTTPS; HTTP is allowed only on loopback for tests")


def _http(method: str, url: str, *, token: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(_safe_url(url), data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        if exc.code in {401, 403}:
            raise NotionConnectorError("the Notion integration token was rejected") from exc
        raise NotionConnectorError(f"Notion returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise NotionConnectorError(f"Notion could not be reached: {exc}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise NotionConnectorError("Notion response exceeded the local size limit")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotionConnectorError("Notion returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise NotionConnectorError("Notion returned an unexpected JSON shape")
    return value


def _rich_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(str(item.get("plain_text") or "") for item in value if isinstance(item, dict))


def _page_title(page: Mapping[str, Any]) -> str:
    properties = page.get("properties") if isinstance(page.get("properties"), dict) else {}
    for value in properties.values():
        if isinstance(value, dict) and value.get("type") == "title":
            title = _rich_text(value.get("title"))
            if title.strip():
                return title.strip()
    return "Untitled Notion page"


def _page_properties(page: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "object": page.get("object"),
        "title": _page_title(page),
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "archived": page.get("archived"),
    }


def _block_text(block: Mapping[str, Any]) -> str:
    block_type = block.get("type")
    value = block.get(block_type) if isinstance(block_type, str) else None
    if not isinstance(value, dict):
        if block_type == "child_page" and isinstance(block.get("child_page"), dict):
            return str(block["child_page"].get("title") or "")
        return ""
    if block_type == "code":
        return _rich_text(value.get("rich_text"))
    if block_type == "to_do":
        return ("[x] " if value.get("checked") else "[ ] ") + _rich_text(value.get("rich_text"))
    if block_type in {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "quote", "callout"}:
        return _rich_text(value.get("rich_text"))
    if block_type == "child_page":
        return str(value.get("title") or "")
    return _rich_text(value.get("rich_text"))


class NotionCredentialStore:
    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise NotionConnectorError("Notion token storage requires the keyring package") from exc
        return keyring

    def save(self, token: str) -> None:
        try:
            self._keyring().set_password(self.service, "token", token.strip())
        except Exception as exc:
            raise NotionConnectorError(f"the Notion token could not be saved to the system credential store: {exc}") from exc

    def load(self) -> str | None:
        try:
            value = self._keyring().get_password(self.service, "token")
        except Exception as exc:
            raise NotionConnectorError(f"the Notion token could not be read from the system credential store: {exc}") from exc
        return value if isinstance(value, str) and value else None

    def delete(self) -> None:
        try:
            self._keyring().delete_password(self.service, "token")
        except Exception:
            return


class NotionConnector:
    def __init__(self, state_path: Path, *, store: NotionCredentialStore | None = None) -> None:
        self.state_path = Path(state_path)
        self.store = store or NotionCredentialStore()

    def _default_state(self) -> dict[str, Any]:
        now = _now()
        return {
            "schema_version": 1,
            "auth_status": "not_configured",
            "account_name": None,
            "error": None,
            "last_checked_at": None,
            "created_at": now,
            "updated_at": now,
        }

    def _read(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return self._default_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NotionConnectorError("Notion connection state is not valid JSON") from exc
        state = self._default_state()
        state.update({key: value[key] for key in state if isinstance(value, dict) and key in value})
        return state

    def _write(self, state: Mapping[str, Any]) -> dict[str, Any]:
        value = {**self._default_state(), **state, "updated_at": _now()}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)
        return value

    def status(self) -> dict[str, Any]:
        state = self._read()
        if state["auth_status"] == "connected" and self.store.load() is None:
            state = self._write({**state, "auth_status": "error", "error": "Notion token is missing; connect again.", "account_name": None})
        return state

    def configure(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token.strip() or len(token) > 500 or "\x00" in token:
            raise NotionConnectorError("a Notion integration token is required")
        account = _http("GET", f"{NOTION_API}/users/me", token=token.strip())
        bot = account.get("bot") if isinstance(account.get("bot"), dict) else {}
        name = account.get("name") if isinstance(account.get("name"), str) else None
        owner = bot.get("owner") if isinstance(bot.get("owner"), dict) else {}
        if not name and isinstance(owner.get("workspace"), bool):
            name = "Notion integration"
        self.store.save(token)
        return self._write({
            **self._read(),
            "auth_status": "connected",
            "account_name": name,
            "error": None,
            "last_checked_at": _now(),
        })

    def test(self) -> dict[str, Any]:
        token = self.store.load()
        if not token:
            raise NotionConnectorError("connect Notion before testing it")
        account = _http("GET", f"{NOTION_API}/users/me", token=token)
        name = account.get("name") if isinstance(account.get("name"), str) else None
        return self._write({**self._read(), "auth_status": "connected", "account_name": name, "error": None, "last_checked_at": _now()})

    def disconnect(self) -> dict[str, Any]:
        self.store.delete()
        return self._write({**self._read(), "auth_status": "not_configured", "account_name": None, "error": "Notion disconnected.", "last_checked_at": None})

    def search(self, *, query: str = "", page_size: int = 10) -> dict[str, Any]:
        token = self.store.load()
        if not token:
            raise NotionConnectorError("connect Notion before searching")
        if not isinstance(query, str) or len(query) > 500:
            raise NotionConnectorError("Notion query must be under 500 characters")
        if not isinstance(page_size, int) or not 1 <= page_size <= 50:
            raise NotionConnectorError("Notion result count must be between 1 and 50")
        value = _http("POST", f"{NOTION_API}/search", token=token, body={
            "query": query,
            "page_size": page_size,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        })
        results = value.get("results") if isinstance(value.get("results"), list) else []
        pages = [_page_properties(item) for item in results if isinstance(item, dict) and item.get("object") == "page"]
        return {"query": query, "count": len(pages[:page_size]), "pages": pages[:page_size]}

    def read_page(self, page_id: str, *, max_blocks: int = 100) -> dict[str, Any]:
        token = self.store.load()
        if not token:
            raise NotionConnectorError("connect Notion before reading a page")
        if not isinstance(page_id, str) or not page_id.strip() or len(page_id) > 200 or "/" in page_id:
            raise NotionConnectorError("Notion page id is invalid")
        if not isinstance(max_blocks, int) or not 1 <= max_blocks <= 200:
            raise NotionConnectorError("Notion block limit must be between 1 and 200")
        value = _http("GET", f"{NOTION_API}/blocks/{urllib.parse.quote(page_id, safe='')}/children?page_size={max_blocks}", token=token)
        blocks = value.get("results") if isinstance(value.get("results"), list) else []
        lines: list[str] = []
        for block in blocks[:max_blocks]:
            if not isinstance(block, dict):
                continue
            text = _block_text(block)
            if text.strip():
                lines.append(text.strip())
        return {"page_id": page_id, "text": "\n".join(lines)[:40000], "block_count": len(blocks), "truncated": len(blocks) > max_blocks or len("\n".join(lines)) > 40000}
