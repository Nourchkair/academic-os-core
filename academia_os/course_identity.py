from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .config import SEMESTER_PATTERN


def course_code(course_name: str) -> str:
    """Return the code portion used by the workspace's canonical course naming."""
    return course_name.split(" - ", 1)[0].strip() if " - " in course_name else course_name.split()[0]


def course_records(semester_root: Path) -> list[dict[str, Any]]:
    """Return recognized course directories using the workspace structure."""
    root = Path(semester_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        return []
    result: list[dict[str, Any]] = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        course_marker = candidate / "01_COURSE"
        if course_marker.is_symlink() or not course_marker.is_dir():
            continue
        result.append({"id": candidate.name, "code": course_code(candidate.name), "name": candidate.name, "path": str(candidate)})
    return result


def resolve_course_identifier(courses: Iterable[Mapping[str, Any]], identifier: str) -> dict[str, Any]:
    """Resolve an exact course id, code, or name to one canonical course.

    Matching is case-insensitive but never partial. Duplicate matches are
    rejected so callers cannot silently select one of multiple courses.
    """
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("course identifier is required")
    requested = identifier.strip().casefold()
    matches: dict[str, dict[str, Any]] = {}
    for raw_course in courses:
        if not isinstance(raw_course, Mapping):
            continue
        course = dict(raw_course)
        fields = {str(course.get(key, "")).strip().casefold() for key in ("id", "code", "name", "course_name")}
        name = str(course.get("name", "")).strip()
        if " - " in name:
            fields.add(name.split(" - ", 1)[1].strip().casefold())
        if requested not in fields:
            continue
        identity = str(course.get("id") or course.get("name") or "").strip()
        if identity:
            matches.setdefault(identity, course)
    if not matches:
        raise KeyError(f"course not found: {identifier}")
    if len(matches) > 1:
        raise ValueError(f"course identifier is ambiguous: {identifier}")
    return next(iter(matches.values()))


def resolve_course_directory(workspace_root: Path, semester: str, identifier: str) -> Path:
    """Resolve a course identifier against a recognized semester structure."""
    if SEMESTER_PATTERN.fullmatch(semester) is None:
        raise ValueError("semester must use a term and four-digit year")
    root = Path(workspace_root).expanduser().resolve()
    semester_root = root / semester
    if semester_root.is_symlink() or not semester_root.is_dir():
        raise KeyError(f"semester not found: {semester}")
    course = resolve_course_identifier(course_records(semester_root), identifier)
    return Path(str(course["path"]))


def source_course_id(workspace_root: Path, source_path: Path) -> str | None:
    """Return structural course ownership for a workspace source.

    A file in a recognized course subtree belongs to that course. A file in a
    semester-level ``00_INBOX`` or directly at semester level is unassigned.
    Unknown workspace folders are rejected rather than assigned by filename.
    """
    root = Path(workspace_root).expanduser().resolve()
    candidate = Path(source_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("source reference must remain inside the recognized academic workspace") from exc
    if not relative.parts or ".academia" in relative.parts:
        raise ValueError("source reference must identify recognized academic material")
    semester = relative.parts[0]
    semester_root = root / semester
    if SEMESTER_PATTERN.fullmatch(semester) is None or semester_root.is_symlink() or not semester_root.is_dir():
        raise ValueError("source reference must identify a recognized academic semester")
    if len(relative.parts) == 1:
        return None
    if relative.parts[1] == "00_INBOX":
        if (semester_root / "00_INBOX").is_dir():
            return None
        raise ValueError("source reference must identify recognized academic material")
    course_root = semester_root / relative.parts[1]
    records = course_records(semester_root)
    recognized = next((record for record in records if record["id"] == course_root.name), None)
    if recognized is None:
        raise ValueError("source reference must identify recognized academic material")
    return str(recognized["id"])
