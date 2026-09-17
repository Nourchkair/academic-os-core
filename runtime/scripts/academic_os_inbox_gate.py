#!/usr/bin/env python3
"""Local Academia OS inbox gate with retryable processing state.

The gate only detects work. It never acknowledges processing. A downstream
agent or worker must begin, verify, and acknowledge a record explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


for candidate in (
    os.environ.get("ACADEMIA_OS_RUNTIME_DIR", ""),
    os.environ.get("ACADEMIC_OS_INSTALL_DIR", ""),
    str(Path(__file__).resolve().parents[2]),
):
    if candidate:
        resolved = str(Path(candidate).expanduser().resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

from academia_os.processing import ProcessingStatus, ProcessingStore  # noqa: E402

IGNORED_NAMES = {".DS_Store", ".gitkeep"}


def default_config_path() -> Path:
    return Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser()


def load_profile(config_path: Path | None = None) -> dict[str, Any]:
    path = (config_path or default_config_path()).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid Academia OS profile: {path}")
    return data


def academic_root(profile: dict[str, Any]) -> Path:
    root = profile.get("academic", {}).get("root_directory")
    if not isinstance(root, str) or not root.strip():
        raise ValueError("profile academic.root_directory is missing")
    return Path(root).expanduser().resolve()


def runtime_directory(profile: dict[str, Any]) -> Path:
    runtime = profile.get("runtime", {}).get("install_directory")
    if not isinstance(runtime, str) or not runtime.strip():
        runtime = profile.get("hermes", {}).get("install_directory")
    if not isinstance(runtime, str) or not runtime.strip():
        runtime = str(Path.home() / ".academic-os")
    return Path(runtime).expanduser().resolve()


def state_path(profile: dict[str, Any]) -> Path:
    """Return the single authoritative workspace operational-state path."""
    return academic_root(profile) / ".academia" / "processing.json"


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
            current[str(path)] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "inode": int(getattr(stat, "st_ino", 0))}
    return current, [str(path) for path in inboxes]


def scan(config_path: Path | None = None) -> dict[str, Any]:
    profile = load_profile(config_path)
    store = ProcessingStore(state_path(profile))
    recovered = store.recover_stale()
    current, inboxes = inventory(profile)
    changed: list[dict[str, Any]] = []
    recovered_sources = {record.source_path for record in recovered}
    for path, signature_data in current.items():
        signature = json.dumps(signature_data, sort_keys=True, separators=(",", ":"))
        record = store.detect(Path(path), signature=signature)
        newly_detected = store.last_detection_changed
        retryable_failure = record.status is ProcessingStatus.FAILED
        stale_recovery = path in recovered_sources
        if newly_detected or retryable_failure or stale_recovery:
            changed.append(
                {
                    "path": path,
                    "change": "new" if newly_detected and record.retry_count == 0 else "retry",
                    "signature": signature_data,
                    "record_id": record.id,
                    "status": record.status.value,
                    "retry_count": record.retry_count,
                    "failure_reason": record.failure_reason,
                }
            )
    changed.sort(key=lambda item: item["path"])
    if not changed:
        return {"wakeAgent": False}
    return {
        "wakeAgent": True,
        "academic_root": str(academic_root(profile)),
        "changed_inboxes": inboxes,
        "changed_file_count": len(changed),
        "changed_files": changed[:100],
        "processing": changed[:100],
        "pending_count": len(store.pending()),
        "processing_truncated": len(changed) > 100,
    }


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
