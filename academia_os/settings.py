from __future__ import annotations

import copy
from typing import Any

from .config import validate_config

STRUCTURAL_CONFIG_KEYS = {"academic.root_directory", "runtime.install_directory", "academic.semester"}


def get_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    value: Any = config
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted_key)
        value = value[part]
    return value


def set_config_value(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError("configuration key must be a dotted path")
    target = config
    for part in parts[:-1]:
        child = target.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"configuration path is not an object: {part}")
        target = child
    target[parts[-1]] = value


def config_diff(before: dict[str, Any], after: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    keys = sorted(set(before) | set(after))
    for key in keys:
        dotted = f"{prefix}.{key}" if prefix else key
        left, right = before.get(key), after.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            changes.extend(config_diff(left, right, dotted))
        elif left != right:
            changes.append({"key": dotted, "before": left, "after": right, "structural": dotted in STRUCTURAL_CONFIG_KEYS})
    return changes


def update_config(config: dict[str, Any], updates: dict[str, Any], *, approve_structural: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate = copy.deepcopy(config)
    for key, value in updates.items():
        set_config_value(candidate, key, value)
    candidate = validate_config(candidate)
    changes = config_diff(validate_config(copy.deepcopy(config)), candidate)
    structural = [change for change in changes if change["structural"]]
    if structural and not approve_structural:
        raise PermissionError("structural configuration changes require explicit approval")
    return candidate, changes
