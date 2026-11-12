#!/usr/bin/env python3
"""Deterministic JSON-RPC app-server stub for CodexAppServerRuntime tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


MODE = os.environ.get("FAKE_CODEX_MODE", "completed")
CAPTURE = os.environ.get("FAKE_CODEX_CAPTURE")
thread_id = "thread-test"
turn_id = "turn-test"


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def notify(method, params):
    send({"jsonrpc": "2.0", "method": method, "params": params})


def respond(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def tool_result_payload():
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "items": [{"id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md", "name": "week-4-reading.md"}],
                "returned": 1,
                "catalog_limit": 100,
                "truncated": False,
            }),
        }],
        "structuredContent": None,
        "_meta": None,
    }


def completed_turn():
    notify("turn/started", {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress"}})
    notify("item/started", {"threadId": thread_id, "turnId": turn_id, "item": {
        "type": "mcpToolCall", "id": "exec-test", "server": "academia",
        "tool": "academia_library", "status": "inProgress", "arguments": {},
        "readOnlyHint": True, "result": None, "error": None,
    }})
    notify("item/completed", {"threadId": thread_id, "turnId": turn_id, "item": {
        "type": "mcpToolCall", "id": "exec-test", "server": "academia",
        "tool": "academia_library", "status": "completed", "arguments": {},
        "readOnlyHint": True, "result": tool_result_payload(), "error": None,
    }})
    for delta in ("week-4-", "reading", ".md"):
        notify("item/agentMessage/delta", {
            "threadId": thread_id, "turnId": turn_id, "itemId": "msg-test", "delta": delta,
        })
    notify("item/completed", {"threadId": thread_id, "turnId": turn_id, "item": {
        "type": "agentMessage", "id": "msg-test", "text": "week-4-reading.md", "phase": "final_answer",
    }})
    notify("turn/completed", {"threadId": thread_id, "turn": {
        "id": turn_id, "status": "completed", "items": [{
            "type": "agentMessage", "id": "msg-test", "text": "week-4-reading.md", "phase": "final_answer",
        }], "error": None,
    }})


def interrupted_turn():
    notify("turn/started", {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress"}})


def failed_turn():
    notify("turn/started", {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress"}})
    notify("turn/completed", {"threadId": thread_id, "turn": {
        "id": turn_id, "status": "failed", "items": [],
        "error": {"message": "synthetic provider failure"},
    }})


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        respond(request_id, {"userAgent": "fake-codex-app-server", "codexHome": "/tmp/fake", "platformFamily": "unix", "platformOs": "macos"})
    elif method == "thread/start":
        respond(request_id, {"thread": {"id": thread_id}, "model": "gpt-6-luna"})
    elif method == "turn/start":
        if CAPTURE:
            Path(CAPTURE).write_text(json.dumps(message.get("params"), ensure_ascii=False), encoding="utf-8")
        respond(request_id, {"turn": {"id": turn_id}})
        if MODE == "completed":
            completed_turn()
        elif MODE == "failed":
            failed_turn()
        else:
            interrupted_turn()
    elif method == "turn/interrupt":
        respond(request_id, {})
        notify("turn/completed", {"threadId": thread_id, "turn": {
            "id": turn_id, "status": "interrupted", "items": [], "error": None,
        }})
    elif method == "initialized":
        continue
    elif request_id is not None and method:
        respond(request_id, {})
