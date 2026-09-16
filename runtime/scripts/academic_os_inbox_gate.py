#!/usr/bin/env python3
"""Cheap, profile-driven Academic OS inbox change gate for Hermes cron.

The gate prints one JSON object. It records metadata signatures outside the
academic root and emits ``wakeAgent:false`` when nothing changed.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IGNORED_NAMES = {".DS_Store", ".gitkeep"}
STATE_NAME = "academic_os_inbox_gate.json"


def default_config_path() -> Path:
    return Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser()


def load_profile(config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or default_config_path()).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid Academic OS profile: {path}")
    return data


def academic_root(profile: dict[str, Any]) -> Path:
    root = profile.get("academic", {}).get("root_directory")
    if not isinstance(root, str) or not root.strip():
        raise ValueError("profile academic.root_directory is missing")
    return Path(root).expanduser().resolve()


def state_path(profile: dict[str, Any]) -> Path:
    hermes_home = profile.get("hermes", {}).get("home_directory")
    if not isinstance(hermes_home, str) or not hermes_home.strip():
        hermes_home = str(Path.home() / ".hermes")
    return Path(hermes_home).expanduser() / "state" / STATE_NAME


def find_inboxes(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result: list[Path] = []
    for inbox in root.rglob("00_INBOX"):
        if not inbox.is_dir() or "COURSE_TEMPLATE" in inbox.parts:
            continue
        if (inbox.parent / "01_COURSE").is_dir():
            result.append(inbox)
    return sorted(result)


def inventory(profile: dict[str, Any]) -> tuple[dict[str, dict[str, int]], list[str]]:
    current: dict[str, dict[str, int]] = {}
    inboxes = find_inboxes(academic_root(profile))
    for inbox in inboxes:
        try:
            paths = sorted(path for path in inbox.rglob("*") if path.is_file())
        except OSError:
            continue
        for path in paths:
            if path.name in IGNORED_NAMES or path.name.startswith("."):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            current[str(path)] = {
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
                "inode": int(getattr(stat, "st_ino", 0)),
            }
    return current, [str(path) for path in inboxes]


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "files": {}}


def save_state(path: Path, profile: dict[str, Any], files: dict[str, dict[str, int]], inboxes: list[str], changed: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "academic_root": str(academic_root(profile)),
        "inboxes": inboxes,
        "files": files,
        "last_scan_utc": datetime.now(timezone.utc).isoformat(),
        "last_wake": bool(changed),
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def scan(config_path: Path | None = None) -> dict[str, Any]:
    profile = load_profile(config_path)
    state = state_path(profile)
    current, inboxes = inventory(profile)
    previous = load_state(state).get("files", {})
    changed_files = []
    for path, signature in current.items():
        if previous.get(path) != signature:
            changed_files.append(
                {
                    "path": path,
                    "change": "new" if path not in previous else "changed",
                    "signature": signature,
                }
            )
    changed_files.sort(key=lambda item: item["path"])
    save_state(state, profile, current, inboxes, bool(changed_files))
    if not changed_files:
        return {"wakeAgent": False}
    payload: dict[str, Any] = {
        "wakeAgent": True,
        "academic_root": str(academic_root(profile)),
        "changed_inboxes": inboxes,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files[:100],
    }
    if len(changed_files) > 100:
        payload["changed_files_truncated"] = True
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    try:
        print(json.dumps(scan(args.config), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"wakeAgent": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
