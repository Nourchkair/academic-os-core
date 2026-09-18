from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import SEMESTER_PATTERN, validate_config
from .domain import DomainProjection
from .library import list_material
from .state import JsonStateStore


def state_root(config: dict[str, Any]) -> Path:
    normalized = validate_config(config)
    root = Path(normalized["academic"]["root_directory"]).expanduser().resolve() / ".academia"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _course_summary(path: Path, *, material_count: int = 0) -> dict[str, Any]:
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
        "material_count": material_count,
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


def _domain_tasks(root: Path, course_ids: set[str]) -> list[dict[str, Any]]:
    projection = DomainProjection(root / ".academia" / "domain.json")
    tasks: list[dict[str, Any]] = []
    for entity in projection.list():
        entity_type = str(entity.get("entity_type", ""))
        if entity_type not in {"deadline", "assignment"}:
            continue
        course = str(entity.get("course_id", "")).strip()
        title = str(entity.get("title", "")).strip()
        evidence = entity.get("evidence")
        if not course or course not in course_ids or not title or not isinstance(evidence, dict):
            continue
        status = str(entity.get("status", "")).casefold()
        tasks.append(
            {
                "id": f"domain:{entity_type}:{entity.get('id', title)}",
                "title": title,
                "completed": status in {"complete", "completed", "submitted", "graded"},
                "course": course,
                "source": str(evidence.get("source_path", "")),
                "source_location": evidence.get("source_location"),
                "confidence": str(evidence.get("confidence", "unverified")),
                "kind": entity_type,
                "due_date": entity.get("date") or entity.get("deadline"),
            }
        )
    return tasks


def build_workspace_snapshot(config: dict[str, Any], *, persist: bool = True, semester_override: str | None = None) -> dict[str, Any]:
    normalized = validate_config(config)
    root = Path(normalized["academic"]["root_directory"]).expanduser().resolve()
    semester = semester_override or normalized["academic"]["semester"]
    if not SEMESTER_PATTERN.fullmatch(semester):
        raise ValueError("semester must use a term and four-digit year, such as Fall 2026")
    semester_root = root / semester
    available_semesters = sorted(
        candidate.name
        for candidate in root.iterdir()
        if candidate.is_dir() and SEMESTER_PATTERN.fullmatch(candidate.name)
    ) if root.is_dir() else []
    courses = []
    tasks: list[dict[str, Any]] = []
    materials = list_material(root, semester)
    material_counts: dict[str, int] = {}
    for item in materials:
        course_id = item.get("course_id")
        if isinstance(course_id, str):
            material_counts[course_id] = material_counts.get(course_id, 0) + 1
    if semester_root.is_dir():
        for candidate in sorted(semester_root.iterdir()):
            if candidate.is_dir() and (candidate / "01_COURSE").is_dir():
                courses.append(_course_summary(candidate, material_count=material_counts.get(candidate.name, 0)))
                tasks.extend(_extract_tasks(candidate / "01_COURSE" / "Course_Status.md", candidate.name))
    tasks.extend(_domain_tasks(root, {course["id"] for course in courses}))
    # The template checklist is onboarding guidance, not academic workload. Actual
    # tasks should come from course evidence or a structured task file.
    today_path = semester_root / "TODAY.md"
    today_lines = [line.strip() for line in today_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()] if today_path.is_file() else []
    snapshot = {
        "schema_version": 1,
        "academic_root": str(root),
        "semester": semester,
        "available_semesters": available_semesters,
        "timezone": normalized["academic"]["timezone"],
        "student": normalized["student"],
        "courses": courses,
        "tasks": tasks,
        "today": {"path": str(today_path), "exists": today_path.is_file(), "lines": today_lines[:80]},
        "material_count": len(materials),
        "inbox_count": sum(1 for item in materials if item.get("category") == "imports"),
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
