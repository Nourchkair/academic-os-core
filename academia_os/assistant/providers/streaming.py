"""Server-sent-event parsing for OpenAI-compatible chat streams.

Kept separate from the adapters so the wire format can be tested without a
network call, and so a provider that cannot stream can fall back to the
existing non-streaming path unchanged.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Iterator


class StreamParseError(ValueError):
    """The provider sent a stream this client cannot read."""


def iter_sse_events(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Yield decoded ``data:`` payloads from one OpenAI-style SSE response."""

    for raw in lines:
        if isinstance(raw, bytes):
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise StreamParseError("the provider stream was not valid UTF-8") from exc
        else:
            line = str(raw).strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StreamParseError("the provider stream contained invalid JSON") from exc
        if isinstance(value, dict):
            yield value


def text_delta(event: dict[str, Any]) -> str | None:
    """Return the assistant text carried by one streamed chunk, if any."""

    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    return content if isinstance(content, str) and content else None


def reasoning_delta(event: dict[str, Any]) -> str | None:
    """Return provider-specific reasoning text (DeepSeek ``reasoning_content``)."""

    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else None
    if not isinstance(delta, dict):
        return None
    for key in ("reasoning_content", "reasoning"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    return None
