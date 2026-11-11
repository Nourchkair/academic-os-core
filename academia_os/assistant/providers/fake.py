"""Deterministic provider used by tests and the read-only runtime harness."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .base import CancelToken, ProviderAdapter, ProviderRequest, ProviderResponse, response_sequence


class FakeProvider(ProviderAdapter):
    id = "fake"

    def __init__(self, responses: Sequence[ProviderResponse | Mapping[str, Any]]) -> None:
        self._responses = response_sequence(responses)
        self.requests: list[ProviderRequest] = []

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.id,
            "text": True,
            "tool_calling": True,
            "streaming": False,
            "cancellation": True,
            "structured_output": False,
            "image_input": False,
            "hosted": False,
        }

    def complete(self, request: ProviderRequest, *, cancel: CancelToken | None = None) -> ProviderResponse:
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("provider request was cancelled")
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("fake provider script is exhausted")
        return self._responses.pop(0)
