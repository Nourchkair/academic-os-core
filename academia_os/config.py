from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from .semester import resolve_current_semester

CURRENT_CONFIG_VERSION = 2
SEMESTER_PATTERN = re.compile(r"^(Winter|Spring|Summer|Fall) [0-9]{4}$")


def _deep_merge(base: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in defaults.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        elif key not in result:
            result[key] = copy.deepcopy(value)
    return result


def _default_sections() -> dict[str, Any]:
    return {
        "student": {"name": "", "institution": "", "program": ""},
        "academic": {"semester": "", "timezone": "UTC", "root_directory": "", "school_portal": "Not yet specified"},
        "runtime": {"install_directory": str(Path.home() / ".academic-os")},
        "preferences": {"explanation_style": "detailed", "preferred_format": "markdown", "use_visuals": True, "study_method": "active recall"},
        "integrations": {"gmail": False, "calendar": False, "drive": False, "school_portal": False},
        "automation": {"daily_brief_enabled": True, "daily_brief_time": "09:00", "inbox_processor_enabled": True, "inbox_interval_minutes": 5},
        "acquisition": {"manual_import_enabled": True, "watched_folders": [], "browser_companion_enabled": False, "browser_access_enabled": False, "advanced_browser_enabled": False, "allowed_sites": []},
        "privacy": {"browser_access_enabled": False, "allowed_sites": [], "dedicated_profile_recommended": True},
        "browser": {"name": "auto", "user_data_dir": "", "profile_directory": "", "access_enabled": False, "allowed_sites": []},
        "agents": {
            "hermes": {"enabled": False, "profile": "default", "home_directory": ""},
            "codex": {"enabled": False},
            "claude": {"enabled": False},
            "chatgpt": {"enabled": False},
        },
    }


def _path_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return str(Path(value).expanduser())


def migrate_config(data: dict[str, Any], *, now: datetime | date | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    result = copy.deepcopy(data)
    version = result.get("schema_version", 1)
    if not isinstance(version, int) or version < 1 or version > CURRENT_CONFIG_VERSION:
        raise ValueError(f"unsupported configuration schema version: {version}")
    if version == 1:
        legacy_hermes = result.get("hermes") if isinstance(result.get("hermes"), dict) else {}
        install_directory = legacy_hermes.get("install_directory") or str(Path.home() / ".academic-os")
        result["runtime"] = {"install_directory": install_directory}
        result["agents"] = {
            "hermes": {
                "enabled": bool(legacy_hermes),
                "profile": str(legacy_hermes.get("profile", "default")),
                "home_directory": str(legacy_hermes.get("home_directory", "")),
            },
            "codex": {"enabled": False},
            "claude": {"enabled": False},
            "chatgpt": {"enabled": False},
        }
        timezone_name = str(result.get("academic", {}).get("timezone", "UTC"))
        if result.get("academic", {}).get("semester") == "Current Semester":
            result.setdefault("academic", {})["semester"] = resolve_current_semester(now, timezone_name)
        result["acquisition"] = {
            "manual_import_enabled": True,
            "watched_folders": [],
            "browser_companion_enabled": False,
            "browser_access_enabled": False,
            "advanced_browser_enabled": False,
            "allowed_sites": [],
        }
        result["privacy"] = {"browser_access_enabled": False, "allowed_sites": [], "dedicated_profile_recommended": True}
        result["schema_version"] = CURRENT_CONFIG_VERSION
    defaults = _default_sections()
    result = _deep_merge(result, defaults)
    if not result["academic"].get("semester"):
        result["academic"]["semester"] = resolve_current_semester(now, str(result["academic"].get("timezone", "UTC")))
    return result


def validate_config(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    version = data.get("schema_version")
    if version == 1:
        data = migrate_config(data)
    if version != CURRENT_CONFIG_VERSION and data.get("schema_version") != CURRENT_CONFIG_VERSION:
        raise ValueError(f"schema_version must be {CURRENT_CONFIG_VERSION}")
    result = _deep_merge(data, _default_sections())
    required = {
        "student.name": result["student"].get("name"),
        "student.institution": result["student"].get("institution"),
        "academic.semester": result["academic"].get("semester"),
        "academic.timezone": result["academic"].get("timezone"),
        "academic.root_directory": result["academic"].get("root_directory"),
        "runtime.install_directory": result["runtime"].get("install_directory"),
    }
    for label, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} is required")
    if result["academic"]["semester"] == "Current Semester" or not SEMESTER_PATTERN.fullmatch(result["academic"]["semester"]):
        raise ValueError("academic.semester must be a resolved semester such as 'Fall 2026', not a placeholder")
    if result["academic"]["timezone"] not in available_timezones():
        raise ValueError("academic.timezone must be a valid IANA time zone")
    root = Path(_path_string(result["academic"]["root_directory"], "academic.root_directory")).resolve()
    runtime = Path(_path_string(result["runtime"]["install_directory"], "runtime.install_directory")).resolve()
    if root == Path("/") or runtime == Path("/"):
        raise ValueError("academic and runtime directories cannot be filesystem root")
    if root == runtime or root in runtime.parents or runtime in root.parents:
        raise ValueError("academic and runtime directories must not contain one another")
    interval = result["automation"].get("inbox_interval_minutes", 5)
    if not isinstance(interval, int) or interval < 1:
        raise ValueError("automation.inbox_interval_minutes must be at least 1")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(result["automation"].get("daily_brief_time", "09:00"))):
        raise ValueError("automation.daily_brief_time must use HH:MM")
    result["academic"]["root_directory"] = str(Path(result["academic"]["root_directory"]).expanduser())
    result["runtime"]["install_directory"] = str(Path(result["runtime"]["install_directory"]).expanduser())
    return result


def load_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read Academia OS configuration {path}: {exc}") from exc
    return validate_config(data)


def save_config(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_config(data)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return normalized


def runtime_directory(config: dict[str, Any]) -> Path:
    normalized = config if config.get("schema_version") == CURRENT_CONFIG_VERSION else migrate_config(config)
    return Path(str(normalized["runtime"]["install_directory"])).expanduser().resolve()


def hermes_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = config if config.get("schema_version") == CURRENT_CONFIG_VERSION else migrate_config(config)
    value = normalized.get("agents", {}).get("hermes", {})
    return value if isinstance(value, dict) else {}
