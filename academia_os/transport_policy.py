"""Local transport command allowlist shared by the browser dashboard and CLI.

The Tauri shell keeps a mirrored command check because it cannot import Python
safely at request time. Both surfaces must reject profile overrides, implicit
JSON flags, NUL bytes, and broad processing writes.
"""
from __future__ import annotations

from typing import Sequence

SAFE_COMMANDS = frozenset(
    {
        "status",
        "courses",
        "course",
        "today",
        "tasks",
        "review",
        "activity",
        "workspace",
        "semester",
        "inbox",
        "process",
        "import",
        "domain",
        "history",
        "study",
        "library",
        "desktop",
        "file-preview",
        "extract",
        "migration",
        "settings",
        "capabilities",
        "watch",
        "verify",
        "verify-source",
        "agents",
        "agent",
        "workflow",
    }
)

def validate_command(
    command: str,
    args: Sequence[str],
    *,
    max_arguments: int = 32,
    max_argument_length: int = 1024,
) -> tuple[str, list[str]]:
    if not isinstance(command, str) or not command:
        raise ValueError("command must be a non-empty string")
    if command not in SAFE_COMMANDS:
        raise ValueError(f"dashboard command is not allowed: {command}")
    if isinstance(args, (str, bytes)) or not isinstance(args, Sequence):
        raise ValueError("args must be an array of strings")
    if any(not isinstance(argument, str) for argument in args):
        raise ValueError("args must be an array of strings")
    values = list(args)
    if len(values) > max_arguments:
        raise ValueError(f"at most {max_arguments} command arguments are allowed")
    for argument in values:
        if len(argument) > max_argument_length:
            raise ValueError(f"command arguments are limited to {max_argument_length} characters")
        if "\x00" in argument:
            raise ValueError("command arguments must not contain NUL bytes")
        option = argument.split("=", 1)[0]
        if option in {"--profile", "--json"}:
            raise ValueError(f"browser may not supply {option}")
    if command == "process" and values != ["status"]:
        raise ValueError("the dashboard may only read processing status")
    return command, values
