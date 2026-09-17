from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from academia_os.semester import resolve_current_semester

SKIP_DIRECTORIES = {".git", ".hermes", ".academic-os", "node_modules", "__pycache__", ".venv", "venv"}
SKIP_SUFFIXES = {".crdownload", ".part", ".tmp", ".temp"}
SEMESTER_PATTERN = re.compile(r"^(fall|winter|spring|summer)[ _-]*(\d{4})$", re.IGNORECASE)


@dataclass(frozen=True)
class MigrationItem:
    source: Path
    destination: Path
    relative_path: str
    semester: str
    size: int
    sha256: str

    def as_json(self) -> dict[str, object]:
        value = asdict(self)
        value["source"] = str(self.source)
        value["destination"] = str(self.destination)
        return value


@dataclass(frozen=True)
class MigrationPlan:
    source_root: Path
    academic_root: Path
    current_semester: str
    items: tuple[MigrationItem, ...]
    created_at: str

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    def as_json(self) -> dict[str, object]:
        return {
            "version": 1,
            "source_root": str(self.source_root),
            "academic_root": str(self.academic_root),
            "current_semester": self.current_semester,
            "created_at": self.created_at,
            "item_count": len(self.items),
            "total_size": self.total_size,
            "items": [item.as_json() for item in self.items],
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_semester(parts: Iterable[str]) -> str | None:
    for part in parts:
        match = SEMESTER_PATTERN.fullmatch(part.strip())
        if match:
            return f"{match.group(1).title()} {match.group(2)}"
    return None


def _should_skip_file(path: Path) -> bool:
    return path.name in {".DS_Store", "Thumbs.db"} or path.name.startswith("~$") or path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith(".")


def _iter_source_files(source_root: Path, academic_root: Path) -> Iterable[Path]:
    source_root = source_root.resolve()
    academic_root = academic_root.resolve()
    for current, directories, files in os.walk(source_root):
        current_path = Path(current).resolve()
        directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES and not name.startswith(".")]
        if current_path == academic_root or academic_root in current_path.parents:
            directories[:] = []
            continue
        for filename in files:
            path = current_path / filename
            if not _should_skip_file(path) and path.is_file():
                yield path


def _destination_for(source_root: Path, academic_root: Path, current_semester: str, source_file: Path) -> tuple[Path, str]:
    relative = source_file.relative_to(source_root)
    semester = detect_semester(relative.parts)
    target_semester = semester or current_semester
    bucket = "00_INBOX" if semester is None or semester == current_semester else "99_ARCHIVE"
    destination = academic_root / target_semester / bucket / "LEGACY_IMPORT" / source_root.name / relative
    return destination, target_semester


def build_migration_plan(source_root: Path, academic_root: Path, current_semester: str) -> MigrationPlan:
    source_root = source_root.expanduser().resolve()
    academic_root = academic_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"migration source is not a folder: {source_root}")
    if source_root == academic_root:
        raise ValueError("migration source and new Academic OS root must be different")
    current_semester = current_semester.strip()
    if current_semester.casefold() in {"current semester", "current"}:
        current_semester = resolve_current_semester()
    if not current_semester:
        raise ValueError("current semester is required for migration")
    items: list[MigrationItem] = []
    for source_file in sorted(_iter_source_files(source_root, academic_root)):
        destination, semester = _destination_for(source_root, academic_root, current_semester, source_file)
        items.append(
            MigrationItem(
                source=source_file,
                destination=destination,
                relative_path=source_file.relative_to(source_root).as_posix(),
                semester=semester,
                size=source_file.stat().st_size,
                sha256=sha256_file(source_file),
            )
        )
    return MigrationPlan(source_root, academic_root, current_semester, tuple(items), datetime.now().astimezone().isoformat())


def _collision_safe_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    counter = 1
    while True:
        candidate = destination.with_name(f"{destination.stem} (legacy import {counter}){destination.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def execute_migration_plan(plan: MigrationPlan, *, items: Iterable[MigrationItem] | None = None, mode: str = "copy") -> dict[str, object]:
    if mode not in {"copy", "move"}:
        raise ValueError("migration mode must be copy or move")
    selected = list(items if items is not None else plan.items)
    result: dict[str, object] = {"mode": mode, "selected": len(selected), "copied": 0, "moved": 0, "skipped": 0, "failed": 0, "destinations": [], "failures": []}
    destinations = result["destinations"]
    failures = result["failures"]
    assert isinstance(destinations, list)
    assert isinstance(failures, list)
    for item in selected:
        try:
            if not item.source.is_file():
                raise FileNotFoundError(f"source is missing: {item.source}")
            if sha256_file(item.source) != item.sha256:
                raise ValueError(f"source changed since plan was created: {item.source}")
            destination = _collision_safe_destination(item.destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source, destination)
            if sha256_file(destination) != item.sha256:
                destination.unlink(missing_ok=True)
                raise IOError(f"hash verification failed after copy: {item.source}")
            destinations.append(str(destination))
            if mode == "move":
                item.source.unlink()
                result["moved"] = int(result["moved"]) + 1
            else:
                result["copied"] = int(result["copied"]) + 1
        except Exception as exc:
            result["failed"] = int(result["failed"]) + 1
            failures.append(str(exc))
    return result


def write_migration_plan(plan: MigrationPlan, directory: Path) -> dict[str, Path]:
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "migration-plan.json"
    markdown_path = directory / "MIGRATION_REVIEW.md"
    json_path.write_text(json.dumps(plan.as_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Legacy material migration review",
        "",
        "This plan was generated from a user-selected folder. Review it before importing.",
        "",
        f"- Source: `{plan.source_root}`",
        f"- New Academic OS root: `{plan.academic_root}`",
        f"- Current semester: `{plan.current_semester}`",
        f"- Files discovered: **{len(plan.items)}**",
        f"- Total bytes: **{plan.total_size}**",
        "",
        "## Safety rules",
        "",
        "- Copy is the default; the legacy source remains intact.",
        "- Move is allowed only after each destination hash matches the source hash.",
        "- Existing destinations are never overwritten; collision copies receive a suffix.",
        "- Semester routing is based only on semester text present in the original path.",
        "- Unknown material is routed to `00_INBOX/LEGACY_IMPORT` for review.",
        "- **Do not move files directly from an AI conversation.** Use the app's explicit confirmation.",
        "",
        "## Proposed items",
        "",
    ]
    for item in plan.items:
        lines.append(f"- `{item.relative_path}` → `{item.destination.relative_to(plan.academic_root)}` ({item.size} bytes, `{item.sha256[:12]}…`)")
    if not plan.items:
        lines.append("No eligible files were found.")
    lines.extend(
        [
            "",
            "## AI review prompt",
            "",
            "Review this migration plan and identify likely semester/course groupings using only evidence in file names and contents. Do not invent course identities. Mark uncertain items and propose a destination; do not execute moves. The user must confirm every import.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
