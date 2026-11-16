"""Connect the installed Academia OS MCP server to the local Codex client.

This module only edits the user's ``$CODEX_HOME/config.toml`` (or
``~/.codex/config.toml``). It never runs Codex, reads its credentials, or
changes any other MCP server. Every write keeps a timestamped backup and is
validated as TOML before it replaces the original.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_ACTIONS = ("tasks", "history", "study", "imports", "downloads", "files", "calendar", "structure")
DEFAULT_ACTIONS = ("tasks", "history", "study", "imports", "downloads")
SERVER_NAME = "academia"
HEADER = "[mcp_servers.academia]"


def codex_config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve() / "config.toml"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _academia_command(profile: Path | None) -> tuple[str, list[str], dict[str, str]]:
    profile_path = Path(profile or (Path.home() / ".academic-os" / "profile.json")).expanduser().resolve()
    frozen = bool(getattr(sys, "frozen", False))
    command = str(Path(sys.executable).resolve())
    if frozen:
        args = ["--profile", str(profile_path), "mcp", "serve"]
        environment: dict[str, str] = {}
    else:
        args = ["-m", "academia_os", "--profile", str(profile_path), "mcp", "serve"]
        repository_root = Path(__file__).resolve().parents[1]
        environment = {"PYTHONPATH": str(repository_root)}
    return command, args, environment


def _validated_actions(actions: list[str] | tuple[str, ...] | None) -> list[str]:
    selected = list(dict.fromkeys(str(action) for action in (actions or DEFAULT_ACTIONS)))
    unknown = sorted(set(selected) - set(ALLOWED_ACTIONS))
    if unknown:
        raise ValueError(f"unsupported trusted action category: {', '.join(unknown)}")
    if not selected:
        raise ValueError("select at least one trusted action category")
    return selected


def _server_block(command: str, args: list[str], environment: dict[str, str]) -> str:
    lines = [
        HEADER,
        f"command = {_toml_string(command)}",
        "args = [" + ", ".join(_toml_string(value) for value in args) + "]",
        'default_tools_approval_mode = "approve"',
    ]
    if environment:
        lines.extend(["", "[mcp_servers.academia.env]"])
        lines.extend(f"{key} = {_toml_string(value)}" for key, value in sorted(environment.items()))
    return "\n".join(lines)


def _find_section(lines: list[str]) -> tuple[int, int] | None:
    start = next((index for index, line in enumerate(lines) if line.strip() == HEADER), None)
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped.startswith("[") and stripped != HEADER and not stripped.startswith("[mcp_servers.academia."):
            break
        end += 1
    return start, end


def _replace_server(text: str, block: str) -> str:
    lines = text.splitlines()
    bounds = _find_section(lines)
    if bounds is None:
        prefix = text.rstrip()
        return (prefix + "\n\n" if prefix else "") + block + "\n"
    start, end = bounds
    before = lines[:start]
    after = lines[end:]
    replacement = block.splitlines()
    if before and before[-1].strip():
        before.append("")
    if after and after[0].strip():
        replacement.append("")
    return "\n".join([*before, *replacement, *after]).rstrip() + "\n"


def _remove_server(text: str) -> str:
    lines = text.splitlines()
    bounds = _find_section(lines)
    if bounds is None:
        return text
    start, end = bounds
    remaining = lines[:start] + lines[end:]
    while remaining and not remaining[-1].strip():
        remaining.pop()
    return "\n".join(remaining).rstrip() + "\n" if remaining else ""


def _backup(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.academia-backup-{stamp}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.academia-backup-{stamp}-{counter}")
        counter += 1
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    return backup


def _write(path: Path, text: str, *, backup: bool = True) -> Path | None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"the Codex config is not valid TOML: {exc}") from exc
    saved = _backup(path) if backup else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=".config.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return saved


def _read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"the Codex config could not be read: {exc}") from exc
    return value if isinstance(value, dict) else {}


def status(profile: Path | None = None, *, config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or codex_config_path()).expanduser().resolve()
    config = _read_config(path)
    server = ((config.get("mcp_servers") or {}) if isinstance(config.get("mcp_servers"), dict) else {}).get(SERVER_NAME)
    command, expected_args, _environment = _academia_command(profile)
    actual_args = server.get("args") if isinstance(server, dict) else None
    allow_actions = []
    if isinstance(actual_args, list):
        for index, value in enumerate(actual_args):
            if value == "--allow-action" and index + 1 < len(actual_args):
                allow_actions.append(str(actual_args[index + 1]))
    connected = isinstance(server, dict)
    return {
        "connected": connected,
        "config_path": str(path),
        "command": server.get("command") if isinstance(server, dict) else None,
        "allow_actions": allow_actions,
        "approval_mode": server.get("default_tools_approval_mode") if isinstance(server, dict) else None,
        "expected_command": command,
        "expected_args": expected_args,
        "codex_installed": shutil.which("codex") is not None,
        "matches_current_install": bool(
            connected
            and server.get("command") == command
            and isinstance(actual_args, list)
            and actual_args[:len(expected_args)] == expected_args
        ),
    }


def connect(profile: Path | None = None, actions: list[str] | tuple[str, ...] | None = None, *, config_path: Path | None = None) -> dict[str, Any]:
    selected = _validated_actions(actions)
    path = (config_path or codex_config_path()).expanduser().resolve()
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    command, args, environment = _academia_command(profile)
    for action in selected:
        args.extend(["--allow-action", action])
    block = _server_block(command, args, environment)
    updated = _replace_server(original, block)
    saved = _write(path, updated)
    value = status(profile, config_path=path)
    value["backup_path"] = str(saved) if saved else None
    value["selected_actions"] = selected
    return value


def disconnect(*, config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or codex_config_path()).expanduser().resolve()
    if not path.is_file():
        return status(None, config_path=path)
    original = path.read_text(encoding="utf-8")
    updated = _remove_server(original)
    if updated == original:
        return status(None, config_path=path)
    saved = _write(path, updated)
    value = status(None, config_path=path)
    value["backup_path"] = str(saved) if saved else None
    return value
