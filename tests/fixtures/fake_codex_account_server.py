#!/usr/bin/env python3
"""Deterministic app-server stub for Codex account manager tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MODE = os.environ.get("FAKE_ACCOUNT_MODE", "success")
MARKER = Path(os.environ.get("FAKE_ACCOUNT_MARKER", "")) if os.environ.get("FAKE_ACCOUNT_MARKER") else None
LOGIN_ID = "login-test"


def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def notify(method, params):
    send({"jsonrpc": "2.0", "method": method, "params": params})


def account_read():
    if MARKER is not None and MARKER.exists():
        return {"account": {"type": "chatgpt", "email": "student@example.edu", "planType": "plus", "workspaceName": "Personal"}, "requiresOpenaiAuth": False}
    return {"account": None, "requiresOpenaiAuth": True}


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        respond(request_id, {"userAgent": "fake-codex-account", "codexHome": "/tmp/fake", "platformFamily": "unix", "platformOs": "macos"})
    elif method == "account/read":
        respond(request_id, account_read())
    elif method == "account/login/start":
        if MODE == "cancel":
            respond(request_id, {"type": "chatgptDeviceCode", "loginId": LOGIN_ID, "userCode": "ABCD-EFGH", "verificationUrl": "https://example.test/device"})
            continue
        if MARKER is not None:
            MARKER.write_text("signed-in", encoding="utf-8")
        respond(request_id, {"type": "chatgptDeviceCode", "loginId": LOGIN_ID, "userCode": "ABCD-EFGH", "verificationUrl": "https://example.test/device"})
        notify("account/login/completed", {"loginId": LOGIN_ID, "success": True, "error": None})
    elif method == "account/login/cancel":
        respond(request_id, {"status": "canceled"})
    elif method == "account/logout":
        if MARKER is not None:
            MARKER.unlink(missing_ok=True)
        respond(request_id, {})
    elif method == "initialized":
        continue
    elif request_id is not None and method:
        respond(request_id, {})
