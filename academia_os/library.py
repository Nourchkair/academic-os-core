from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIBRARY_CATEGORIES = ("syllabi", "readings", "notes", "imports", "other")

# These are workspace control files, not academic material. They remain available
# through the workspace and agent interfaces but should not clutter Library.
_WORKSPACE_FILES = frozenset(
    {
        "ACADEMIC_OS_RULES.md",
        "INTEGRATION_STATUS.md",
        "README.md",
        "SEMESTER_STATUS.md",
        "SEMESTER_TASKS.md",
        "TODAY.md",
        "VERIFICATION.md",
    }
)
_COURSE_CONTROL_FILES = frozenset(
    {
        "Brightspace_Log.md",
        "Calendar_Log.md",
        "Communications_Log.md",
        "Course_Context.md",
        "Course_Status.md",
        "Grading.md",
        "Questions.md",
        "Schedule.md",
        "Study_Strategy.md",
        "USER_OVERRIDES.md",
        "Weak_Areas.md",
    }
)


def _category(relative_path: Path) -> str:
    parts = [part.casefold() for part in relative_path.parts]
    filename = relative_path.name.casefold()
    joined = "/".join(parts)

    if "00_inbox" in parts:
        return "imports"
    if "syllabus" in filename or "course guide" in filename or "course_outline" in filename or "course-outline" in filename:
        return "syllabi"
    if "05_reference" in parts or any(token in joined for token in ("reading", "reference", "bibliography", "source_index")):
        return "readings"
    if any(part in {"02_weeks", "04_exams", "06_knowledge"} for part in parts) or any(token in joined for token in ("note", "study", "lecture", "review")):
        return "notes"
    return "other"


def _course_id(semester_root: Path, path: Path) -> str | None:
    relative = path.relative_to(semester_root)
    if not relative.parts:
        return None
    candidate = semester_root / relative.parts[0]
    if candidate.is_dir() and (candidate / "01_COURSE").is_dir():
        return candidate.name
    return None


def _is_material(path: Path, relative: Path) -> bool:
    if path.name in {".DS_Store", ".gitkeep"} or path.name.startswith("."):
        return False
    if ".academia" in relative.parts:
        return False
    if path.name in _WORKSPACE_FILES:
        return False
    if any(part == "01_COURSE" for part in relative.parts) and path.name in _COURSE_CONTROL_FILES:
        return False
    return True


def list_material(workspace_root: Path, semester: str) -> list[dict[str, Any]]:
    """List visible files in one semester without reading or changing their contents.

    Categories are navigation hints based only on explicit folder/name signals. The
    inventory never claims that a file is authoritative or correctly classified.
    Symlinks and files resolving outside the configured workspace are omitted.
    """

    root = Path(workspace_root).expanduser().resolve()
    semester_root = root / semester
    if not semester_root.is_dir():
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(semester_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
            relative = path.relative_to(root)
        except (OSError, ValueError):
            continue
        if not _is_material(path, relative):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "id": relative.as_posix(),
                "name": path.name,
                "path": str(path),
                "relative_path": relative.as_posix(),
                "semester": semester,
                "course_id": _course_id(semester_root, path),
                "category": _category(path.relative_to(semester_root)),
                "extension": path.suffix.lower(),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return items


def filter_material(
    items: list[dict[str, Any]],
    *,
    category: str = "all",
    course_id: str | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    if category != "all" and category not in LIBRARY_CATEGORIES:
        raise ValueError(f"unsupported library category: {category}")
    normalized_query = query.strip().casefold()
    filtered = [
        item
        for item in items
        if (category == "all" or item.get("category") == category)
        and (course_id is None or item.get("course_id") == course_id)
        and (not normalized_query or normalized_query in f"{item.get('name', '')} {item.get('relative_path', '')}".casefold())
    ]
    return sorted(filtered, key=lambda item: (str(item.get("category", "")), str(item.get("relative_path", ""))))
