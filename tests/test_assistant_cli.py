from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "academia_os", *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )


def test_assistant_tools_cli_exposes_only_read_tools() -> None:
    result = run_cli("assistant", "tools", "--json")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["contract_version"] == 1
    assert value["write_tools"] == []
    assert len(value["tools"]) == 12
    assert all(tool["permission"] == "read_local" for tool in value["tools"])
    assert all(tool["side_effect"] == "none" for tool in value["tools"])


def test_assistant_capabilities_cli_reports_the_provider_gate_as_pending() -> None:
    result = run_cli("assistant", "capabilities", "--json")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["runtime"]["status"] == "read_only"
    assert value["runtime"]["write_tools"] is False
    assert value["provider_gate"]["status"] in {"pending", "read_only_passed"}
    assert value["providers"][0]["id"] == "codex-app-server"
    assert value["providers"][0]["read_only"] is True
    assert value["providers"][0]["writes"] is False
    assert len(value["tools"]) == 12
