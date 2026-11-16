"""Shared source identity and workspace path safety.

Study citations, Library metadata, and assistant tools must agree on what a
source version means.  This module is deliberately small and dependency-free so
it can be reused without creating a circular import with the Study domain.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

MAX_SOURCE_BYTES = 64 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_HIDDEN_PARTS = {".academia", ".git", ".hermes", ".academic-os"}


class SourceIdentityError(ValueError):
    """A source path or version is unsafe or unsupported."""


def safe_workspace_path(root: Path, path: str | Path, *, allow_missing: bool = False) -> Path:
    """Resolve a source path inside the workspace without following symlinks."""

    workspace = Path(root).expanduser().resolve()
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else workspace / raw
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as exc:
        raise SourceIdentityError("source must be inside this workspace") from exc
    if not relative.parts:
        raise SourceIdentityError("source path must identify a file inside the workspace")
    current = workspace
    for part in relative.parts:
        if part in {"", ".", ".."} or part.startswith(".") or part.casefold() in _HIDDEN_PARTS:
            raise SourceIdentityError("source paths cannot contain hidden or parent segments")
        current = current / part
        if current.is_symlink():
            raise SourceIdentityError("source paths cannot traverse symbolic links")
    try:
        resolved = candidate.resolve(strict=not allow_missing)
    except OSError as exc:
        raise SourceIdentityError("source path cannot be resolved") from exc
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise SourceIdentityError("source path resolves outside this workspace") from exc
    return resolved


def source_id(root: Path, path: str | Path) -> str:
    """Return a validated workspace-relative POSIX source ID."""

    resolved = safe_workspace_path(root, path)
    return resolved.relative_to(Path(root).expanduser().resolve()).as_posix()


def validate_source_id(root: Path, source_id_value: str, *, semester: str | None = None) -> Path:
    if not isinstance(source_id_value, str) or not source_id_value or "\\" in source_id_value or "\x00" in source_id_value:
        raise SourceIdentityError("source_id must be a workspace-relative POSIX path")
    relative = PurePosixPath(source_id_value)
    if relative.is_absolute() or not relative.parts or relative.as_posix() != source_id_value:
        raise SourceIdentityError("source_id must be a workspace-relative POSIX path")
    if semester is not None and relative.parts[0] != semester:
        raise SourceIdentityError("source_id must belong to the selected semester")
    path = safe_workspace_path(root, Path(*relative.parts))
    if not path.is_file():
        raise SourceIdentityError("source_id must identify a regular file")
    return path


def fingerprint(path: Path, *, max_bytes: int = MAX_SOURCE_BYTES) -> str:
    source = Path(path)
    size = source.stat().st_size
    if size > max_bytes:
        raise SourceIdentityError(f"source must be at most {max_bytes // (1024 * 1024)} MB")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def short_version(value: str, *, length: int = 16) -> str:
    if not isinstance(value, str) or not value:
        raise SourceIdentityError("source digest is required")
    return value[:length]


def identity(path: Path, *, root: Path | None = None, max_bytes: int = MAX_SOURCE_BYTES) -> dict[str, Any]:
    source = Path(path)
    stat = source.stat()
    digest = fingerprint(source, max_bytes=max_bytes)
    value: dict[str, Any] = {
        "name": source.name,
        "sha256": digest,
        "version": short_version(digest),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if root is not None:
        value["source_id"] = source_id(root, source)
    return value
