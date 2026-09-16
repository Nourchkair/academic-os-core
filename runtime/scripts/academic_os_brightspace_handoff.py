#!/usr/bin/env python3
"""Safe school-portal Downloads snapshot/handoff utility.

This is only the acquisition boundary. A human or agent uses the visible,
authenticated browser to retrieve files. This utility snapshots Downloads and
moves only new/changed supported files into a verified course ``00_INBOX``.
It never classifies, submits, answers quizzes, posts messages, or handles
passwords, MFA codes, cookies, or tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".rtf", ".txt"}
IGNORED_NAMES = {".DS_Store"}
TEMPORARY_SUFFIXES = {".crdownload", ".download", ".part", ".tmp"}


def default_install_dir() -> Path:
    return Path(os.environ.get("ACADEMIC_OS_INSTALL_DIR", str(Path.home() / ".academic-os"))).expanduser()


def sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def is_candidate(path: Path) -> bool:
    return path.is_file() and path.name not in IGNORED_NAMES and not path.name.startswith(".") and path.suffix.lower() not in TEMPORARY_SUFFIXES


def is_supported(path: Path) -> bool:
    return is_candidate(path) and path.suffix.lower() in SUPPORTED_EXTENSIONS


def inventory(downloads_dir: Path) -> dict[str, dict[str, Any]]:
    if not downloads_dir.is_dir():
        raise FileNotFoundError(f"Downloads directory does not exist: {downloads_dir}")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(downloads_dir.iterdir()):
        if not is_candidate(path):
            continue
        stat = path.stat()
        result[str(path)] = {
            "path": str(path),
            "name": path.name,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": sha256(path),
            "supported": is_supported(path),
        }
    return result


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def read_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError(f"invalid Downloads manifest: {path}")
    return data


def unique_destination(destination_dir: Path, original_name: str, retrieval_date: str) -> Path:
    candidate = destination_dir / original_name
    if not candidate.exists():
        return candidate
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    candidate = destination_dir / f"{stem} (School Portal {retrieval_date}){suffix}"
    counter = 2
    while candidate.exists():
        candidate = destination_dir / f"{stem} (School Portal {retrieval_date} {counter}){suffix}"
        counter += 1
    return candidate


def course_files(course_dir: Path) -> list[Path]:
    return [path for path in course_dir.rglob("*") if path.is_file() and path.name not in IGNORED_NAMES]


def append_log(course_dir: Path, request: str, retrieval_date: str, moved: list[Path], skipped: list[tuple[str, str]], source_url: str | None) -> None:
    log_path = course_dir / "01_COURSE" / "Brightspace_Log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"\n## {retrieval_date}", f"Requested: {request}"]
    if source_url:
        lines.append(f"Source page: {source_url}")
    lines.append("Downloaded to 00_INBOX:")
    lines.extend(f"- {path.name}" for path in moved) if moved else lines.append("- None")
    if skipped:
        lines.append("Skipped:")
        lines.extend(f"- {name} — {reason}" for name, reason in skipped)
    lines.append(f"Result: {len(moved)} new file(s) sent to 00_INBOX.")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def command_snapshot(args: argparse.Namespace) -> int:
    downloads_dir = Path(args.downloads_dir).expanduser().resolve()
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else default_install_dir() / "state" / "school-portal"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output).expanduser() if args.output else state_dir / f"downloads-before-{timestamp}.json"
    files = inventory(downloads_dir)
    write_json_atomic(output, {"version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(), "downloads_dir": str(downloads_dir), "files": files})
    print(json.dumps({"status": "snapshot_created", "manifest": str(output.resolve()), "file_count": len(files)}, ensure_ascii=False))
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    before = read_manifest(Path(args.before).expanduser().resolve())
    downloads_dir = Path(args.downloads_dir or before.get("downloads_dir", "")).expanduser().resolve()
    course_dir = Path(args.course_dir).expanduser().resolve()
    inbox = course_dir / "00_INBOX"
    if not course_dir.is_dir():
        raise RuntimeError(f"course directory does not exist: {course_dir}")
    if not inbox.is_dir():
        raise RuntimeError(f"course does not have 00_INBOX: {inbox}")
    current = inventory(downloads_dir)
    new_entries = sorted((entry for path, entry in current.items() if before["files"].get(path) != entry), key=lambda entry: entry["name"].lower())
    retrieval_date = datetime.now().astimezone().date().isoformat()
    existing_hashes: dict[str, Path] = {}
    for path in course_files(course_dir):
        try:
            existing_hashes.setdefault(sha256(path), path)
        except OSError:
            continue
    moved: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for entry in new_entries:
        source = Path(entry["path"])
        if not source.is_file():
            skipped.append((entry["name"], "no longer exists"))
            continue
        if not bool(entry.get("supported", is_supported(source))):
            skipped.append((entry["name"], "unsupported or non-academic file type; left in Downloads"))
            continue
        if entry["sha256"] in existing_hashes:
            skipped.append((entry["name"], f"identical content already exists at {existing_hashes[entry['sha256']].relative_to(course_dir)}"))
            continue
        destination = unique_destination(inbox, entry["name"], retrieval_date)
        shutil.move(str(source), str(destination))
        existing_hashes[entry["sha256"]] = destination
        moved.append(destination)
    append_log(course_dir, args.request, retrieval_date, moved, skipped, args.source_url)
    print(json.dumps({"status": "handoff_complete", "course_dir": str(course_dir), "inbox": str(inbox), "request": args.request, "detected_new_or_changed_files": len(new_entries), "moved_to_inbox": [str(path) for path in moved], "skipped": [{"name": name, "reason": reason} for name, reason in skipped], "inbox_processor_invoked": False}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--downloads-dir", default=str(Path.home() / "Downloads"))
    snapshot.add_argument("--state-dir")
    snapshot.add_argument("--output")
    snapshot.set_defaults(handler=command_snapshot)
    handoff = sub.add_parser("handoff")
    handoff.add_argument("--before", required=True)
    handoff.add_argument("--course-dir", required=True)
    handoff.add_argument("--request", required=True)
    handoff.add_argument("--source-url")
    handoff.add_argument("--downloads-dir")
    handoff.set_defaults(handler=command_handoff)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except (FileNotFoundError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
