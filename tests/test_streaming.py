from __future__ import annotations

import pytest

from academia_os.assistant.providers.streaming import StreamParseError, iter_sse_events, reasoning_delta, text_delta


def test_iter_sse_events_decodes_and_stops_at_done() -> None:
    lines = [
        b': keep-alive\n',
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
        b'\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
        b'data: [DONE]\n',
        b'data: {"choices":[{"delta":{"content":"ignored"}}]}\n',
    ]
    events = list(iter_sse_events(lines))
    assert [text_delta(event) for event in events] == ["Hel", "lo"]


def test_reasoning_delta_reads_deepseek_field() -> None:
    event = {"choices": [{"delta": {"reasoning_content": "Because"}}]}
    assert reasoning_delta(event) == "Because"
    assert text_delta(event) is None


def test_iter_sse_events_rejects_invalid_json() -> None:
    with pytest.raises(StreamParseError):
        list(iter_sse_events([b'data: {not json}\n']))
