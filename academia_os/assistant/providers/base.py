"""Provider-neutral assistant interfaces."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class ProviderToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str = ""
    tool_calls: tuple[ProviderToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    context: str = ""


class CancelToken:
    """Small provider-neutral cancellation primitive."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class ProviderAdapter(Protocol):
    id: str

    def capabilities(self) -> dict[str, Any]:
        ...

    def complete(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> ProviderResponse:
        ...


def normalize_response(value: ProviderResponse | Mapping[str, Any]) -> ProviderResponse:
    if isinstance(value, ProviderResponse):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("provider response must be an object")
    calls = value.get("tool_calls", ())
    normalized_calls = tuple(
        call if isinstance(call, ProviderToolCall) else ProviderToolCall(
            name=str(call.get("name", "")),
            arguments=dict(call.get("arguments", {})),
            call_id=call.get("call_id"),
        )
        for call in calls
    )
    return ProviderResponse(
        text=str(value.get("text", "")),
        tool_calls=normalized_calls,
        finish_reason=str(value.get("finish_reason", "stop")),
        usage=dict(value.get("usage", {})),
    )


def response_sequence(values: Sequence[ProviderResponse | Mapping[str, Any]]) -> list[ProviderResponse]:
    return [normalize_response(value) for value in values]
