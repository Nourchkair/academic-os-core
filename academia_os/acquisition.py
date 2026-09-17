from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import validate_config
from .processing import ProcessingStore


def browser_access_policy(config: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_config(config)
    acquisition = normalized["acquisition"]
    privacy = normalized["privacy"]
    enabled = bool(acquisition.get("browser_access_enabled", False) and privacy.get("browser_access_enabled", False))
    return {"enabled": enabled, "allowed_sites": list(privacy.get("allowed_sites", [])), "dedicated_profile_recommended": bool(privacy.get("dedicated_profile_recommended", True))}


@dataclass(frozen=True)
class AcquisitionSource:
    source_type: str
    label: str
    browser: str | None = None
    source_url: str | None = None
    acquired_at: str = ""
    original_file: str | None = None


def acquisition_defaults() -> dict[str, Any]:
    return {
        "manual_import_enabled": True,
        "watched_folders": [],
        "browser_companion_enabled": False,
        "browser_access_enabled": False,
        "advanced_browser_enabled": False,
        "allowed_sites": [],
    }


def capability_report() -> dict[str, dict[str, Any]]:
    return {
        "manual_import": {"status": "supported", "description": "User-selected local files are staged for review."},
        "watched_folders": {"status": "supported", "description": "Configured local folders can be scanned without browser access."},
        "browser_companion": {"status": "planned", "description": "A future explicit Send to Academia OS companion interface."},
        "chromium": {"status": "supported", "mode": "visible_handoff_only", "description": "Optional Chromium-family visible handoff may be used when explicitly configured; no credential/session data is read."},
        "firefox": {"status": "planned", "description": "No Firefox automation adapter is claimed yet."},
        "safari": {"status": "planned", "description": "No Safari automation adapter is claimed yet."},
    }


def configured_watched_folders(config: dict[str, Any]) -> list[Path]:
    normalized = validate_config(config)
    return [Path(value).expanduser().resolve() for value in normalized["acquisition"].get("watched_folders", []) if isinstance(value, str) and value.strip()]


def scan_watched_folder(path: Path, *, since: datetime | None = None) -> list[Path]:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        return []
    candidates: list[Path] = []
    for item in sorted(path.rglob("*")):
        if not item.is_file() or item.name.startswith(".") or item.suffix.lower() in {".part", ".crdownload", ".tmp"}:
            continue
        if since is not None:
            modified = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
            if modified <= since:
                continue
        candidates.append(item)
    return candidates


def import_file(source: Path, destination_inbox: Path, processing: ProcessingStore | None = None) -> dict[str, Any]:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination_inbox = Path(destination_inbox).expanduser().resolve()
    destination_inbox.mkdir(parents=True, exist_ok=True)
    destination = destination_inbox / source.name
    counter = 1
    while destination.exists():
        destination = destination_inbox / f"{source.stem} (import {counter}){source.suffix}"
        counter += 1
    shutil.copy2(source, destination)
    metadata = {"source_type": "manual_file", "original_file": str(source), "acquired_at": datetime.now(timezone.utc).isoformat(), "destination": str(destination)}
    if processing is not None:
        processing.detect(destination, signature=f"{destination.stat().st_size}:{destination.stat().st_mtime_ns}")
    return metadata
