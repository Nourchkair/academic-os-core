"""Provider-neutral API model connections and model routing.

API keys live in the macOS Keychain. The connection state file contains only
provider metadata, discovered model ids, status, and routing preferences. No
secret is written to the academic workspace.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

KEYCHAIN_SERVICE = "academia-os-model-credentials"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MODEL_LIMIT = 500
ROLES = ("default", "fast", "deep", "vision", "image")

CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "openai",
        "name": "OpenAI",
        "kind": "api",
        "default_base_url": "https://api.openai.com/v1",
        "auth": "bearer",
        "models_path": "/models",
        "docs": "Create an API key at platform.openai.com.",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "kind": "api",
        "default_base_url": "https://api.anthropic.com/v1",
        "auth": "x-api-key",
        "models_path": "/models",
        "docs": "Create an API key at console.anthropic.com.",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "kind": "api",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "auth": "x-goog-api-key",
        "models_path": "/models",
        "docs": "Create an API key in Google AI Studio.",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "kind": "api",
        "default_base_url": "https://openrouter.ai/api/v1",
        "auth": "bearer",
        "models_path": "/models",
        "docs": "One API key for many providers, billed by OpenRouter.",
    },
    {
        "id": "groq",
        "name": "Groq",
        "kind": "api",
        "default_base_url": "https://api.groq.com/openai/v1",
        "auth": "bearer",
        "models_path": "/models",
        "docs": "Create an API key in the Groq console.",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "api",
        "default_base_url": "https://api.deepseek.com",
        "auth": "bearer",
        "models_path": "/models",
        "docs": "Create an API key in the DeepSeek platform.",
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "kind": "api",
        "default_base_url": "https://api.mistral.ai/v1",
        "auth": "bearer",
        "models_path": "/models",
        "docs": "Create an API key in the Mistral console.",
    },
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "kind": "local",
        "default_base_url": "http://127.0.0.1:11434",
        "auth": "none",
        "models_path": "/api/tags",
        "docs": "Run models locally; no API key is needed.",
    },
    {
        "id": "lmstudio",
        "name": "LM Studio (local)",
        "kind": "local",
        "default_base_url": "http://127.0.0.1:1234/v1",
        "auth": "none",
        "models_path": "/models",
        "docs": "Start the LM Studio local server; no API key is needed by default.",
    },
    {
        "id": "custom",
        "name": "Custom OpenAI-compatible",
        "kind": "api",
        "default_base_url": "",
        "auth": "bearer-optional",
        "models_path": "/models",
        "docs": "Use an OpenAI-compatible HTTPS endpoint, or a loopback HTTP server.",
    },
)


class ModelConnectionError(ValueError):
    """A model provider operation failed safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _catalog_entry(provider_id: str) -> dict[str, Any]:
    for entry in CATALOG:
        if entry["id"] == provider_id:
            return dict(entry)
    raise ModelConnectionError("unknown model provider preset")


def _safe_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or "\x00" in value:
        raise ModelConnectionError("provider base URL is invalid")
    parts = urllib.parse.urlsplit(value.strip())
    if parts.username or parts.password or parts.fragment:
        raise ModelConnectionError("provider base URL must not include credentials or a fragment")
    if parts.scheme == "https" and parts.hostname:
        return value.strip().rstrip("/")
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip().rstrip("/")
    raise ModelConnectionError("provider URLs must use HTTPS; HTTP is allowed only for loopback local servers")


def _http(url: str, *, headers: Mapping[str, str], timeout: float = 20.0) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(_safe_url(url), method="GET", headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ModelConnectionError("provider response exceeded the local size limit")
            return response.status, {key.lower(): value for key, value in response.headers.items()}, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, payload
    except (OSError, urllib.error.URLError) as exc:
        raise ModelConnectionError(f"provider could not be reached: {exc}") from exc


def _request(url: str, headers: Mapping[str, str]) -> dict[str, Any]:
    status, _headers, payload = _http(url, headers=headers)
    if status < 200 or status >= 300:
        if status in {401, 403}:
            raise ModelConnectionError("the API key was rejected by the provider")
        raise ModelConnectionError(f"provider returned HTTP {status}")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelConnectionError("provider returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ModelConnectionError("provider returned an unexpected JSON shape")
    return value


def _model_capabilities(provider_id: str, raw: Mapping[str, Any]) -> list[str]:
    name = str(raw.get("id") or raw.get("name") or "").casefold()
    capabilities = ["chat"]
    if provider_id in {"anthropic", "gemini"} or any(token in name for token in ("gpt-4o", "gpt-4.1", "gpt-5", "vision", "gemini")):
        capabilities.append("vision")
    if any(token in name for token in ("o1", "o3", "o4", "reasoning", "thinking")):
        capabilities.append("reasoning")
    if any(token in name for token in ("image", "dall-e", "imagen")):
        capabilities.append("image")
    if raw.get("context_length") and isinstance(raw["context_length"], int):
        capabilities.append(f"context:{raw['context_length']}")
    return capabilities


def _normalize_models(provider_id: str, value: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_items: list[Any]
    if provider_id == "ollama":
        raw_items = value.get("models") if isinstance(value.get("models"), list) else []
    elif provider_id == "gemini":
        raw_items = value.get("models") if isinstance(value.get("models"), list) else []
    else:
        raw_items = value.get("data") if isinstance(value.get("data"), list) else []
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        if provider_id == "gemini":
            model_id = raw.get("name")
            if isinstance(model_id, str) and model_id.startswith("models/"):
                model_id = model_id.split("/", 1)[1]
            methods = raw.get("supportedGenerationMethods")
            if isinstance(methods, list) and "generateContent" not in methods:
                continue
            name = raw.get("displayName") if isinstance(raw.get("displayName"), str) else model_id
        elif provider_id == "ollama":
            model_id = raw.get("name") or raw.get("model")
            name = model_id
        else:
            model_id = raw.get("id")
            name = raw.get("name") if isinstance(raw.get("name"), str) else model_id
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append({
            "id": model_id,
            "name": str(name or model_id),
            "capabilities": _model_capabilities(provider_id, raw),
        })
    models.sort(key=lambda item: item["name"].casefold())
    return models[:MODEL_LIMIT]


def _fetch_models(provider: Mapping[str, Any], base_url: str, api_key: str) -> list[dict[str, Any]]:
    url = f"{base_url}{provider['models_path']}"
    headers = {"Accept": "application/json"}
    auth = provider["auth"]
    if auth == "bearer" or auth == "bearer-optional":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif auth == "x-api-key":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif auth == "x-goog-api-key":
        headers["x-goog-api-key"] = api_key
    value = _request(url, headers)
    models = _normalize_models(str(provider["id"]), value)
    if not models:
        raise ModelConnectionError("the provider returned no usable models")
    return models


class ModelCredentialStore:
    """Keychain-backed API keys owned by the local sidecar."""

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise ModelConnectionError("API key storage requires the keyring package") from exc
        return keyring

    def _account(self, provider_id: str) -> str:
        return f"provider:{provider_id}"

    def save(self, provider_id: str, api_key: str) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ModelConnectionError("API key is required")
        try:
            self._keyring().set_password(self.service, self._account(provider_id), api_key.strip())
        except Exception as exc:
            raise ModelConnectionError(f"the API key could not be saved to the system credential store: {exc}") from exc

    def load(self, provider_id: str) -> str | None:
        try:
            value = self._keyring().get_password(self.service, self._account(provider_id))
        except Exception as exc:
            raise ModelConnectionError(f"the API key could not be read from the system credential store: {exc}") from exc
        return value if isinstance(value, str) and value else None

    def delete(self, provider_id: str) -> None:
        try:
            self._keyring().delete_password(self.service, self._account(provider_id))
        except Exception:
            return


class ModelConnectionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _default(self) -> dict[str, Any]:
        return {"schema_version": 1, "providers": [], "preferences": {role: None for role in ROLES}}

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._default()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelConnectionError("model connection state is not valid JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("providers"), list):
            raise ModelConnectionError("model connection state has an unsupported structure")
        state = self._default()
        state.update({key: value[key] for key in state if key in value})
        if not isinstance(state["preferences"], dict):
            state["preferences"] = {role: None for role in ROLES}
        return state

    def _write(self, state: Mapping[str, Any]) -> dict[str, Any]:
        value = self._default()
        value.update(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return value


class ModelConnectionManager:
    def __init__(self, state_path: Path, *, credentials: ModelCredentialStore | None = None) -> None:
        self.store = ModelConnectionStore(state_path)
        self.credentials = credentials or ModelCredentialStore()

    def catalog(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in CATALOG]

    def list(self) -> dict[str, Any]:
        state = self.store._read()
        return {
            "providers": list(state["providers"]),
            "preferences": dict(state["preferences"]),
            "catalog": self.catalog(),
        }

    def add(self, *, provider: str, api_key: str = "", base_url: str = "", name: str = "") -> dict[str, Any]:
        entry = _catalog_entry(provider)
        if not isinstance(api_key, str):
            raise ModelConnectionError("API key must be text")
        base = _safe_url(base_url or entry["default_base_url"]) if (base_url or entry["default_base_url"]) else ""
        if not base:
            raise ModelConnectionError("a base URL is required for this provider")
        auth = entry["auth"]
        if auth in {"bearer", "x-api-key", "x-goog-api-key"} and not api_key.strip():
            raise ModelConnectionError("an API key is required for this provider")
        models = _fetch_models(entry, base, api_key.strip())
        if api_key.strip() and auth != "none":
            self.credentials.save(provider, api_key)
        else:
            self.credentials.delete(provider)
        state = self.store._read()
        record = {
            "id": provider,
            "name": name.strip() or entry["name"],
            "kind": entry["kind"],
            "base_url": base,
            "auth": "none" if auth == "none" else "configured",
            "status": "connected",
            "enabled": True,
            "models": models,
            "last_checked_at": _now(),
            "error": None,
            "created_at": next((item.get("created_at") for item in state["providers"] if item.get("id") == provider), _now()),
            "updated_at": _now(),
        }
        state["providers"] = [item for item in state["providers"] if item.get("id") != provider] + [record]
        return self.store._write(state)

    def test(self, provider: str) -> dict[str, Any]:
        entry = _catalog_entry(provider)
        state = self.store._read()
        record = next((item for item in state["providers"] if item.get("id") == provider), None)
        if record is None:
            raise ModelConnectionError("provider is not configured")
        key = self.credentials.load(provider) or ""
        if entry["auth"] in {"bearer", "x-api-key", "x-goog-api-key"} and not key:
            raise ModelConnectionError("the provider API key is missing; add it again")
        try:
            models = _fetch_models(entry, str(record["base_url"]), key)
        except ModelConnectionError as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            record["updated_at"] = _now()
            state["providers"] = [record if item.get("id") == provider else item for item in state["providers"]]
            self.store._write(state)
            raise
        record.update({"status": "connected", "models": models, "error": None, "last_checked_at": _now(), "updated_at": _now()})
        state["providers"] = [record if item.get("id") == provider else item for item in state["providers"]]
        return self.store._write(state)

    def remove(self, provider: str) -> dict[str, Any]:
        state = self.store._read()
        if not any(item.get("id") == provider for item in state["providers"]):
            raise ModelConnectionError("provider is not configured")
        self.credentials.delete(provider)
        state["providers"] = [item for item in state["providers"] if item.get("id") != provider]
        for role, value in list(state["preferences"].items()):
            if isinstance(value, str) and value.startswith(f"{provider}/"):
                state["preferences"][role] = None
        return self.store._write(state)

    def set_enabled(self, provider: str, enabled: bool) -> dict[str, Any]:
        state = self.store._read()
        record = next((item for item in state["providers"] if item.get("id") == provider), None)
        if record is None:
            raise ModelConnectionError("provider is not configured")
        record["enabled"] = bool(enabled)
        record["updated_at"] = _now()
        state["providers"] = [record if item.get("id") == provider else item for item in state["providers"]]
        return self.store._write(state)

    def set_preferences(self, values: Mapping[str, Any]) -> dict[str, Any]:
        state = self.store._read()
        available = {
            f"{record['id']}/{model['id']}"
            for record in state["providers"]
            if record.get("status") == "connected" and record.get("enabled", True)
            for model in record.get("models", [])
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        }
        preferences = dict(state["preferences"])
        for role in ROLES:
            if role not in values:
                continue
            value = values[role]
            if value is None or value == "":
                preferences[role] = None
            elif not isinstance(value, str) or value not in available:
                raise ModelConnectionError(f"{role} model must be one of the enabled provider models")
            else:
                preferences[role] = value
        state["preferences"] = preferences
        return self.store._write(state)
