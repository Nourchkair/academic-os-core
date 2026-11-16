from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from academia_os.assistant.providers.api import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider
from academia_os.assistant.providers.base import CancelToken, ProviderRequest


class FakeChatServer:
    def __init__(self) -> None:
        self.openai_bodies: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _json(self, value: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _sse(self) -> None:
                """Write one OpenAI-style stream, then close the connection."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (
                    {"choices": [{"delta": {"reasoning_content": "Checking the reading"}}]},
                    {"choices": [{"delta": {"content": "Streamed "}}]},
                    {"choices": [{"delta": {"content": "answer."}}]},
                ):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True

            def do_GET(self) -> None:
                if self.path == "/v1/models":
                    self._json({"data": [{"id": "gpt-test", "object": "model"}]})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path.endswith("/chat/completions"):
                    owner.openai_bodies.append(body)
                    if body.get("stream"):
                        self._sse()
                    elif any(message.get("role") == "tool" for message in body.get("messages", [])):
                        self._json({"choices": [{"message": {"role": "assistant", "content": "API final answer"}, "finish_reason": "stop"}]})
                    else:
                        self._json({"choices": [{"message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "task_list", "arguments": json.dumps({"course": "POL 2103"})},
                            }],
                        }, "finish_reason": "tool_calls"}]})
                elif self.path.endswith("/messages"):
                    self._json({
                        "content": [
                            {"type": "text", "text": "Anthropic answer"},
                            {"type": "tool_use", "id": "toolu-1", "name": "task_list", "input": {"course": "POL 2103"}},
                        ],
                        "stop_reason": "tool_use",
                    })
                elif ":generateContent" in self.path:
                    self._json({
                        "candidates": [{
                            "content": {"parts": [{"text": "Gemini answer"}]},
                            "finishReason": "STOP",
                        }],
                        "usageMetadata": {"totalTokenCount": 10},
                    })
                else:
                    self._json({"error": "not found"}, 404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


TOOLS = ({"name": "task.list", "description": "List tasks", "input_schema": {"type": "object", "properties": {}}},)


def test_openai_compatible_provider_maps_text_and_tool_calls() -> None:
    server = FakeChatServer()
    try:
        provider = OpenAICompatibleProvider(provider_id="openai", base_url=server.origin + "/v1", api_key="key", model="gpt-test")
        request = ProviderRequest(messages=({"role": "user", "content": "List my tasks"},), tools=TOOLS, context="system context")
        first = provider.complete(request)
        assert first.tool_calls[0].name == "task.list"
        assert first.tool_calls[0].call_id == "call-1"
        assert first.finish_reason == "tool_calls"
        assert server.openai_bodies[0]["messages"][0] == {"role": "system", "content": "system context"}
        assert server.openai_bodies[0]["tools"][0]["function"]["name"] == "task_list"

        followup = ProviderRequest(messages=(
            {"role": "user", "content": "List my tasks"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "name": "task.list", "arguments": {"course": "POL 2103"}}]},
            {"role": "tool", "name": "task.list", "tool_call_id": "call-1", "content": "[]"},
        ), tools=TOOLS, context="system context")
        second = provider.complete(followup)
        assert second.text == "API final answer"
        assert second.tool_calls == ()
    finally:
        server.close()


def test_openai_compatible_provider_streams_text_and_reasoning() -> None:
    server = FakeChatServer()
    try:
        provider = OpenAICompatibleProvider(provider_id="openai", base_url=server.origin + "/v1", api_key="key", model="gpt-test")
        request = ProviderRequest(messages=({"role": "user", "content": "Explain"},), tools=TOOLS, context="system context")
        assert list(provider.stream(request)) == [
            ("reasoning", "Checking the reading"),
            ("text", "Streamed "),
            ("text", "answer."),
        ]
        body = server.openai_bodies[-1]
        assert body["stream"] is True
        assert body["tools"][0]["function"]["name"] == "task_list"
    finally:
        server.close()


def test_openai_compatible_provider_stream_stops_when_cancelled() -> None:
    server = FakeChatServer()
    try:
        provider = OpenAICompatibleProvider(provider_id="openai", base_url=server.origin + "/v1", api_key="key", model="gpt-test")
        cancel = CancelToken()
        cancel.cancel()
        request = ProviderRequest(messages=({"role": "user", "content": "Explain"},), tools=())
        assert list(provider.stream(request, cancel=cancel)) == []
        assert server.openai_bodies == []
    finally:
        server.close()


def test_tool_names_are_sanitized_for_provider_apis() -> None:
    from academia_os.assistant.providers.api import _tool_name_map

    mapping = _tool_name_map([{"name": "mcp.call"}, {"name": "task.list"}, {"name": "task_list"}])

    assert mapping == {"mcp.call": "mcp_call", "task.list": "task_list", "task_list": "task_list_2"}


def test_anthropic_provider_returns_text_and_tool_use() -> None:
    server = FakeChatServer()
    try:
        provider = AnthropicProvider(provider_id="anthropic", base_url=server.origin + "/v1", api_key="key", model="claude-test")
        result = provider.complete(ProviderRequest(messages=({"role": "user", "content": "List tasks"},), tools=TOOLS, context="system"))
        assert result.text == "Anthropic answer"
        assert result.tool_calls[0].name == "task.list"
        assert result.tool_calls[0].call_id == "toolu-1"
    finally:
        server.close()


def test_gemini_provider_returns_text() -> None:
    server = FakeChatServer()
    try:
        provider = GeminiProvider(provider_id="gemini", base_url=server.origin + "/v1beta", api_key="key", model="gemini-test")
        result = provider.complete(ProviderRequest(messages=({"role": "user", "content": "List tasks"},), tools=TOOLS, context="system"))
        assert result.text == "Gemini answer"
        assert result.usage["totalTokenCount"] == 10
    finally:
        server.close()
