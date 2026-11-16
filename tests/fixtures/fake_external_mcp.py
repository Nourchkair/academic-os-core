#!/usr/bin/env python3
"""Deterministic external MCP server for connection-manager tests."""
from __future__ import annotations

import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        respond(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "Fake Research", "version": "1.0"},
        })
    elif method == "tools/list":
        respond(request_id, {"tools": [
            {
                "name": "search_notes",
                "description": "Search local research notes without changing them.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "read_note",
                "description": "Read one note.",
                "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            },
            {
                "name": "write_note",
                "description": "Modify a note.",
                "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
        ]})
    elif method == "tools/call":
        respond(request_id, {"content": [{"type": "text", "text": "ok"}]})
    elif method == "initialized":
        continue
    elif request_id is not None and method:
        respond(request_id, {})
