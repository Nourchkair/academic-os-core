"""Compatibility facade for the legacy Tkinter desktop.

New interfaces should import from ``academia_os`` directly. This module keeps
existing imports working while delegating all domain behavior to the neutral
core.
"""
from __future__ import annotations

import os
import platform
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from academia_os.config import hermes_config
from academia_os.discovery import AcademicFolderCandidate, discover_academic_folders
from academia_os.semester import resolve_current_semester, semester_suggestions as _semester_suggestions
from academia_os.timezones import (
    COMMON_TIMEZONES,
    FRIENDLY_TIMEZONES,
    detect_local_timezone,
    friendly_timezone_choices,
    friendly_timezone_label,
    timezone_choices,
    timezone_from_friendly_label,
)
from academia_os.workspace import build_workspace_snapshot
from installer.core import copy_tree_non_destructive, validate_manifest


def semester_suggestions(now: datetime | date | None = None) -> list[str]:
    current = resolve_current_semester(now)
    return [f"Current semester — {current}", *_semester_suggestions(now)]


def create_course_from_template(
    academic_root: Path,
    semester: str,
    course_code: str,
    course_title: str,
    template_root: Path,
    manifest: dict[str, Any],
) -> Path:
    code = " ".join(course_code.strip().split())
    title = " ".join(course_title.strip().split())
    if not code or not title:
        raise ValueError("course code and title are required")
    validate_manifest(manifest)
    if semester.lower().startswith("current semester"):
        semester = manifest["academic"]["semester"]
    destination = academic_root.expanduser() / semester.strip() / f"{code} - {title}"
    if destination.exists():
        raise FileExistsError(f"course folder already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy_tree_non_destructive(template_root, destination, manifest, allow_existing=False)
    return destination


def load_dashboard(profile_path: Path) -> dict[str, Any]:
    profile = __import__("academia_os.config", fromlist=["load_config"]).load_config(profile_path.expanduser().resolve())
    snapshot = build_workspace_snapshot(profile)
    root = Path(snapshot["academic_root"])
    runtime = Path(profile["runtime"]["install_directory"]).expanduser().resolve()
    courses = [course["name"] for course in snapshot["courses"]]
    today_preview = "\n".join(snapshot["today"]["lines"][:8])
    return {
        "student_name": str(profile["student"]["name"]),
        "institution": str(profile["student"]["institution"]),
        "program": str(profile["student"].get("program", "")),
        "semester": snapshot["semester"],
        "timezone": str(profile["academic"]["timezone"]),
        "academic_root": str(root),
        "install_root": str(runtime),
        "course_count": len(courses),
        "courses": courses,
        "inbox_count": sum(int(course["inbox_count"]) for course in snapshot["courses"]),
        "today_preview": today_preview,
        "root_exists": root.is_dir(),
        "semester_exists": (root / snapshot["semester"]).is_dir(),
        "integrations": profile.get("integrations", {}),
        "hermes_enabled": bool(hermes_config(profile).get("enabled")),
        "review_count": snapshot["review_count"],
        "tasks": snapshot["tasks"],
    }


def open_local_path(path: Path) -> None:
    path = path.expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


__all__ = [
    "AcademicFolderCandidate", "COMMON_TIMEZONES", "FRIENDLY_TIMEZONES", "create_course_from_template", "detect_local_timezone",
    "discover_academic_folders", "friendly_timezone_choices", "friendly_timezone_label", "load_dashboard", "open_local_path",
    "semester_suggestions", "timezone_choices", "timezone_from_friendly_label",
]
