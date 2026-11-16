"""Preflight for campus material imports.

Reads only metadata: size, extension, and a content hash when the file is small
enough to be worth it. Nothing is copied. Duplicate detection compares against
the exact destination inbox, so the student sees "already here" before the copy
happens rather than after.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

MAX_HASH_BYTES = 256 * 1024 * 1024
EXTRACTABLE = {
    ".pdf", ".docx", ".pptx", ".txt", ".text", ".md", ".markdown",
    ".csv", ".json", ".yaml", ".yml",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
OCR_CANDIDATES = {".pdf"}


class PreflightError(ValueError):
    """The destination or the selection cannot be inspected safely."""


def _digest(path: Path) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_HASH_BYTES:
        return None
    sha = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(block)
    except OSError:
        return None
    return sha.hexdigest()


def _destination_inbox(workspace_root: Path, destination: str) -> Path:
    import os

    root = Path(workspace_root).expanduser().resolve()
    candidate = Path(destination).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    workspace_prefix = str(root) + os.sep
    if not str(candidate.resolve()).startswith(workspace_prefix):
        raise PreflightError("the destination must stay inside the workspace")
    inbox = candidate.resolve()
    if inbox.name != "00_INBOX":
        raise PreflightError("imports must target a 00_INBOX folder")
    if not inbox.is_dir():
        raise PreflightError("the destination inbox does not exist")
    return inbox


def _existing(destination: Path) -> Iterable[Path]:
    try:
        return [path for path in destination.iterdir() if path.is_file()]
    except OSError:
        return []


def preflight(paths: list[str], destination: str, workspace_root: Path) -> dict[str, Any]:
    """Return one inspection record per requested file without copying anything."""

    inbox = _destination_inbox(workspace_root, destination)
    existing = _existing(inbox)
    records: list[dict[str, Any]] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw).expanduser()
        record: dict[str, Any] = {"path": str(path), "name": path.name, "status": "ready"}
        try:
            size = path.stat().st_size if path.is_file() else None
        except OSError:
            size = None
        if size is None:
            records.append({**record, "status": "missing", "reason": "this file is not readable yet; if it lives in iCloud or OneDrive, download it first"})
            continue
        extension = path.suffix.lower()
        digest = _digest(path)
        duplicate = None
        for candidate in existing:
            same_name = candidate.name == path.name
            same_size = False
            try:
                same_size = candidate.stat().st_size == size
            except OSError:
                same_size = False
            if not same_name and not same_size:
                continue
            identical = False
            if digest and same_size:
                identical = _digest(candidate) == digest
            duplicate = {
                "name": candidate.name,
                "path": str(candidate),
                "identical": identical,
                "same_name": same_name,
            }
            break
        records.append({
            **record,
            "size": size,
            "extension": extension,
            "extractable": extension in EXTRACTABLE,
            "ocr_may_be_needed": extension in OCR_CANDIDATES,
            "image": extension in IMAGE_EXTENSIONS,
            "duplicate": duplicate,
        })
    return {
        "destination": str(inbox),
        "files": records,
        "ready": sum(1 for record in records if record.get("status") == "ready"),
        "duplicates": sum(1 for record in records if record.get("duplicate")),
    }
