from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import validate_config
from .state import JsonStateStore


def state_root(config: dict[str, Any]) -> Path:
    normalized = validate_config(config)
    root = Path(normalized["academic"]["root_directory"]).expanduser().resolve() / ".academia"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _course_summary(path: Path) -> dict[str, Any]:
    name = path.name
    code = name.split(" - ", 1)[0].strip() if " - " in name else name.split()[0]
    inbox = path / "00_INBOX"
    inbox_count = sum(1 for item in inbox.rglob("*") if item.is_file() and item.name not in {".gitkeep", ".DS_Store"}) if inbox.is_dir() else 0
    status_file = path / "01_COURSE" / "Course_Status.md"
    return {
        "id": name,
        "code": code,
        "name": name,
        "path": str(path),
        "inbox_count": inbox_count,
        "status_file": str(status_file) if status_file.is_file() else None,
        "review_required": inbox_count > 0,
    }


def _extract_tasks(path: Path, course: str | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    tasks: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        match = re.match(r"\s*- \[([ xX])\]\s+(.*)", line)
        if not match:
            continue
        tasks.append({"id": f"{path}:{line_number}", "title": match.group(2).strip(), "completed": match.group(1).lower() == "x", "course": course, "source": str(path), "source_line": line_number, "confidence": "unverified"})
    return tasks


def build_workspace_snapshot(config: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    normalized = validate_config(config)
    root = Path(normalized["academic"]["root_directory"]).expanduser().resolve()
    semester = normalized["academic"]["semester"]
    semester_root = root / semester
    courses = []
    tasks: list[dict[str, Any]] = []
    if semester_root.is_dir():
        for candidate in sorted(semester_root.iterdir()):
            if candidate.is_dir() and (candidate / "01_COURSE").is_dir():
                courses.append(_course_summary(candidate))
                tasks.extend(_extract_tasks(candidate / "01_COURSE" / "Course_Status.md", candidate.name))
    # The template checklist is onboarding guidance, not academic workload. Actual
    # tasks should come from course evidence or a structured task file.
    today_path = semester_root / "TODAY.md"
    today_lines = [line.strip() for line in today_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()] if today_path.is_file() else []
    snapshot = {
        "schema_version": 1,
        "academic_root": str(root),
        "semester": semester,
        "timezone": normalized["academic"]["timezone"],
        "student": normalized["student"],
        "courses": courses,
        "tasks": tasks,
        "today": {"path": str(today_path), "exists": today_path.is_file(), "lines": today_lines[:80]},
        "review_count": sum(1 for item in courses if item["review_required"]),
        "workspace_exists": root.is_dir(),
    }
    if persist:
        JsonStateStore(root / ".academia" / "index.json").write(snapshot)
    return snapshot


def load_workspace_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    root = Path(validate_config(config)["academic"]["root_directory"]).expanduser().resolve()
    index = root / ".academia" / "index.json"
    if index.is_file():
        try:
            return json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return build_workspace_snapshot(config)
