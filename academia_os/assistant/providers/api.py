"""HTTP model providers used by the provider-neutral assistant runtime.

These adapters are intentionally non-streaming in this slice. They support the
same read-only tool contract as the Codex provider; proposal tools remain
Codex-only until each provider's tool-call path has the same Review coverage.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Iterator, Mapping

from .base import CancelToken, ProviderRequest, ProviderResponse, ProviderToolCall

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT = 180.0
USER_AGENT = "AcademiaOS/1.0 (academic study assistant)"


class ApiProviderError(RuntimeError):
    """The provider request failed safely."""


def _safe_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiProviderError("provider base URL is missing")
    parts = urllib.parse.urlsplit(value.strip())
    if parts.username or parts.password or parts.fragment:
        raise ApiProviderError("provider base URL must not include credentials or a fragment")
    if parts.scheme == "https" and parts.hostname:
        return value.strip().rstrip("/")
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value.strip().rstrip("/")
    raise ApiProviderError("provider URLs must use HTTPS; HTTP is allowed only for loopback local servers")


def _post(url: str, headers: Mapping[str, str], body: Mapping[str, Any], *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    request = urllib.request.Request(
        _safe_url(url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json", **dict(headers)},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        try:
            detail = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = {}
        message = ""
        if isinstance(detail, dict):
            error = detail.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            elif isinstance(error, str):
                message = error
            if not message and isinstance(detail.get("message"), str):
                message = detail["message"]
        if exc.code in {401, 403}:
            raise ApiProviderError("the provider rejected the API key") from exc
        if exc.code == 429:
            raise ApiProviderError("the provider rate limit was reached; try again later") from exc
        raise ApiProviderError(f"provider returned HTTP {exc.code}{': ' + message if message else ''}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ApiProviderError(f"provider could not be reached: {exc}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ApiProviderError("provider response exceeded the local size limit")
    try:
        value = json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiProviderError("provider returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ApiProviderError("provider returned an unexpected JSON shape")
    return value


def _openai_messages(request: ProviderRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if request.context:
        messages.append({"role": "system", "content": request.context})
    for message in request.messages:
        role = message.get("role")
        if role == "tool":
            messages.append({
                "role": "tool",
                "tool_call_id": str(message.get("tool_call_id") or message.get("name") or "tool"),
                "content": str(message.get("content") or ""),
            })
            continue
        if role == "assistant":
            tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            entry: dict[str, Any] = {"role": "assistant", "content": str(message.get("content") or "") or None}
            if tool_calls:
                entry["tool_calls"] = [{
                    "id": str(call.get("id") or call.get("call_id") or f"call-{index}"),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                    },
                } for index, call in enumerate(tool_calls) if isinstance(call, dict)]
            messages.append(entry)
            continue
        messages.append({"role": "user", "content": str(message.get("content") or "")})
    return messages


def _openai_tools(request: ProviderRequest) -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    } for tool in request.tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]


class OpenAICompatibleProvider:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT, session_id: str | None = None) -> None:
        self.id = f"api:{provider_id}"
        self.base_url = _safe_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.session_id = session_id

    def capabilities(self) -> dict[str, Any]:
        return {"streaming": False, "tools": True, "images": True}

    def complete(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> ProviderResponse:
        if cancel is not None and cancel.cancelled:
            return ProviderResponse(finish_reason="cancelled")
        url = f"{self.base_url}/chat/completions"
        if self.id.endswith(":ollama") and not self.base_url.endswith("/v1"):
            url = f"{self.base_url}/v1/chat/completions"
        body: dict[str, Any] = {"model": self.model, "messages": _openai_messages(request)}
        tools = _openai_tools(request)
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if self.id == "api:opencode-go":
            headers["x-opencode-session"] = self.session_id or uuid.uuid4().hex
        value = _post(url, headers, body, timeout=self.timeout)
        choices = value.get("choices") if isinstance(value.get("choices"), list) else []
        if not choices or not isinstance(choices[0], dict):
            raise ApiProviderError("provider returned no choices")
        message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
        text = message.get("content") if isinstance(message.get("content"), str) else ""
        calls: list[ProviderToolCall] = []
        raw_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not name:
                continue
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) and arguments else {}
            except json.JSONDecodeError as exc:
                raise ApiProviderError("provider returned invalid tool arguments") from exc
            calls.append(ProviderToolCall(name=name, arguments=parsed if isinstance(parsed, dict) else {}, call_id=str(raw.get("id") or "")))
        return ProviderResponse(
            text=text,
            tool_calls=tuple(calls),
            finish_reason=str(choices[0].get("finish_reason") or "stop"),
            usage=value.get("usage") if isinstance(value.get("usage"), dict) else {},
        )



    def stream(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> Iterator[tuple[str, str]]:
        """Yield ("text" | "reasoning", chunk) tuples from an OpenAI-style stream."""

        from .streaming import iter_sse_events, reasoning_delta, text_delta

        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {"model": self.model, "messages": _openai_messages(request), "stream": True}
        tools = _openai_tools(request)
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if self.id == "api:opencode-go":
            headers["x-opencode-session"] = self.session_id or uuid.uuid4().hex
        http_request = urllib.request.Request(
            _safe_url(url),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "text/event-stream", **headers},
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                for event in iter_sse_events(response):
                    if cancel is not None and cancel.cancelled:
                        return
                    reasoning = reasoning_delta(event)
                    if reasoning:
                        yield ("reasoning", reasoning)
                    text = text_delta(event)
                    if text:
                        yield ("text", text)
        except urllib.error.HTTPError as exc:
            raise ApiProviderError(f"provider returned HTTP {exc.code}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ApiProviderError(f"provider could not be reached: {exc}") from exc


def _anthropic_messages(request: ProviderRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        role = message.get("role")
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or message.get("name") or "tool"),
                "content": str(message.get("content") or ""),
            }
            if messages and messages[-1].get("role") == "user" and isinstance(messages[-1].get("content"), list):
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = str(message.get("content") or "")
            if text:
                blocks.append({"type": "text", "text": text})
            raw_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            for index, call in enumerate(raw_calls):
                if not isinstance(call, dict):
                    continue
                blocks.append({
                    "type": "tool_use",
                    "id": str(call.get("id") or call.get("call_id") or f"call-{index}"),
                    "name": str(call.get("name") or ""),
                    "input": call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
                })
            messages.append({"role": "assistant", "content": blocks or text})
            continue
        messages.append({"role": "user", "content": str(message.get("content") or "")})
    return messages


class AnthropicProvider:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.id = f"api:{provider_id}"
        self.base_url = _safe_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        return {"streaming": False, "tools": True, "images": True}

    def complete(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> ProviderResponse:
        if cancel is not None and cancel.cancelled:
            return ProviderResponse(finish_reason="cancelled")
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": _anthropic_messages(request),
        }
        if request.context:
            body["system"] = request.context
        tools = [{
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
        } for tool in request.tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
        if tools:
            body["tools"] = tools
        value = _post(
            f"{self.base_url}/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            body,
            timeout=self.timeout,
        )
        content = value.get("content") if isinstance(value.get("content"), list) else []
        text_parts: list[str] = []
        calls: list[ProviderToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                calls.append(ProviderToolCall(
                    name=block["name"],
                    arguments=block.get("input") if isinstance(block.get("input"), dict) else {},
                    call_id=str(block.get("id") or ""),
                ))
        return ProviderResponse(
            text="".join(text_parts),
            tool_calls=tuple(calls),
            finish_reason=str(value.get("stop_reason") or "stop"),
            usage=value.get("usage") if isinstance(value.get("usage"), dict) else {},
        )


def _gemini_contents(request: ProviderRequest) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        role = message.get("role")
        if role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {
                    "name": str(message.get("name") or "tool"),
                    "response": {"result": str(message.get("content") or "")},
                }}],
            })
            continue
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            text = str(message.get("content") or "")
            if text:
                parts.append({"text": text})
            raw_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            for call in raw_calls:
                if isinstance(call, dict) and isinstance(call.get("name"), str):
                    parts.append({"functionCall": {
                        "name": call["name"],
                        "args": call.get("arguments") if isinstance(call.get("arguments"), dict) else {},
                    }})
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            continue
        contents.append({"role": "user", "parts": [{"text": str(message.get("content") or "")}]})
    return contents


class GeminiProvider:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.id = f"api:{provider_id}"
        self.base_url = _safe_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        return {"streaming": False, "tools": True, "images": True}

    def complete(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> ProviderResponse:
        if cancel is not None and cancel.cancelled:
            return ProviderResponse(finish_reason="cancelled")
        body: dict[str, Any] = {
            "contents": _gemini_contents(request),
            "generationConfig": {"maxOutputTokens": 4096},
        }
        if request.context:
            body["systemInstruction"] = {"parts": [{"text": request.context}]}
        declarations = [{
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        } for tool in request.tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]
        if declarations:
            body["tools"] = [{"functionDeclarations": declarations}]
        model = urllib.parse.quote(self.model, safe="")
        value = _post(
            f"{self.base_url}/models/{model}:generateContent",
            {"x-goog-api-key": self.api_key},
            body,
            timeout=self.timeout,
        )
        candidates = value.get("candidates") if isinstance(value.get("candidates"), list) else []
        if not candidates or not isinstance(candidates[0], dict):
            raise ApiProviderError("provider returned no candidates")
        content = candidates[0].get("content") if isinstance(candidates[0].get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        text_parts: list[str] = []
        calls: list[ProviderToolCall] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            if isinstance(part.get("functionCall"), dict):
                function = part["functionCall"]
                if isinstance(function.get("name"), str):
                    calls.append(ProviderToolCall(
                        name=function["name"],
                        arguments=function.get("args") if isinstance(function.get("args"), dict) else {},
                        call_id=None,
                    ))
        return ProviderResponse(
            text="".join(text_parts),
            tool_calls=tuple(calls),
            finish_reason=str(candidates[0].get("finishReason") or "stop"),
            usage=value.get("usageMetadata") if isinstance(value.get("usageMetadata"), dict) else {},
        )
