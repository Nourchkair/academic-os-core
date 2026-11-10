from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .processing import ProcessingStore
from .state import JsonStateStore


LIBRARY_CATEGORIES = ("syllabi", "readings", "lectures", "assessments", "notes", "other")
LIBRARY_LOCATIONS = ("all", "inbox", "organized")
LIBRARY_PROCESSING_STATUSES = (
    "all",
    "not_processed",
    "in_progress",
    "processed",
    "failed",
    "untracked",
)

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

    # Match common human-written variants such as "Course Outline", as well
    # as underscore and hyphen forms. This comes before broad knowledge-folder
    # rules so a verified outline is not mislabeled as ordinary notes.
    normalized_name = " ".join("".join(char if char.isalnum() else " " for char in filename).split())
    if any(token in normalized_name for token in ("syllabus", "syllabi", "course guide", "course outline")):
        return "syllabi"
    if "03_assignments" in parts or "04_exams" in parts or any(
        token in normalized_name.split()
        for token in ("assignment", "exam", "quiz", "test", "midterm", "final", "essay", "project", "presentation", "assessment")
    ):
        return "assessments"
    if "02_lectures" in parts or any(
        token in normalized_name.split()
        for token in ("lecture", "lectures", "slide", "slides", "recording")
    ):
        return "lectures"
    if "source_verification" in parts:
        return "notes"
    if "05_reference" in parts or any(
        token in normalized_name.split()
        for token in ("reading", "readings", "reference", "references", "bibliography", "chapter")
    ) or "source index" in normalized_name:
        return "readings"
    if any(part in {"02_weeks", "06_knowledge"} for part in parts) or any(
        token in normalized_name.split()
        for token in ("note", "notes", "study", "review", "summary", "guide", "verification")
    ):
        return "notes"
    return "other"


def _processing_bucket(item: dict[str, Any]) -> str:
    status = str(item.get("processing_status", "")).upper()
    if status == "FAILED":
        return "failed"
    if status in {"PROCESSING", "VERIFIED"}:
        return "in_progress"
    if status in {"DETECTED", "PENDING"}:
        return "not_processed"
    if status == "ACKNOWLEDGED":
        return "processed"
    return "not_processed" if item.get("intake_status") == "inbox" else "untracked"


def _intake_status(relative_path: Path) -> str:
    """Report intake location separately from a file's academic material type."""
    return "inbox" if "00_inbox" in {part.casefold() for part in relative_path.parts} else "organized"


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
    if "STUDY" in relative.parts and path.name == "study.json":
        return False
    if ".academia" in relative.parts:
        return False
    if any(part.casefold() == "_templates" for part in relative.parts):
        return False
    if path.name in _WORKSPACE_FILES:
        return False
    if any(part == "01_COURSE" for part in relative.parts) and path.name in _COURSE_CONTROL_FILES:
        return False
    if any(part == "03_ASSIGNMENTS" for part in relative.parts) and path.name == "Assignment_History.json":
        return False
    return True


def _acquisition_index(workspace_root: Path) -> dict[str, dict[str, Any]]:
    path = workspace_root / ".academia" / "acquisition.json"
    if not path.is_file():
        return {}
    value = JsonStateStore(path).read({"records": {}})
    records = value.get("records") if isinstance(value, dict) else {}
    return {
        str(key): item
        for key, item in records.items()
        if isinstance(item, dict) and item.get("provenance") in {"ORIGINAL", "USER-CREATED", "AI-GENERATED", "EXTERNAL"}
    } if isinstance(records, dict) else {}


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
    acquisitions = _acquisition_index(root)
    processing_records = {
        str(Path(record.source_path).expanduser().resolve()): record
        for record in ProcessingStore(root / ".academia" / "processing.json").list()
    }

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
        if any(part.casefold() == "ai_generated" for part in relative.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        acquisition = acquisitions.get(relative.as_posix())
        semester_relative = path.relative_to(semester_root)
        base_category = _category(semester_relative)
        intake_status = _intake_status(semester_relative)
        items.append(
            {
                "id": relative.as_posix(),
                "name": path.name,
                "path": str(path),
                "relative_path": relative.as_posix(),
                "semester": semester,
                "course_id": _course_id(semester_root, path),
                "category": base_category,
                "intake_status": intake_status,
                "extension": path.suffix.lower(),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "provenance": acquisition.get("provenance") if acquisition else None,
                "source_type": acquisition.get("source_type") if acquisition else ("Imported" if intake_status == "inbox" else "Workspace material"),
                **({
                    "processing_status": processing_records[str(resolved)].status.value,
                    "extraction_status": (processing_records[str(resolved)].verification or {}).get("extraction_status"),
                } if str(resolved) in processing_records else {}),
            }
        )
    return items


def filter_material(
    items: list[dict[str, Any]],
    *,
    category: str = "all",
    location: str = "all",
    processing_status: str = "all",
    course_id: str | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    if category != "all" and category not in LIBRARY_CATEGORIES:
        raise ValueError(f"unsupported library category: {category}")
    if location not in LIBRARY_LOCATIONS:
        raise ValueError(f"unsupported library location: {location}")
    if processing_status not in LIBRARY_PROCESSING_STATUSES:
        raise ValueError(f"unsupported library processing status: {processing_status}")
    normalized_query = query.strip().casefold()
    filtered = [
        item
        for item in items
        if (category == "all" or item.get("category") == category)
        and (location == "all" or item.get("intake_status") == location)
        and (processing_status == "all" or _processing_bucket(item) == processing_status)
        and (course_id is None or item.get("course_id") == course_id)
        and (not normalized_query or normalized_query in f"{item.get('name', '')} {item.get('relative_path', '')}".casefold())
    ]
    return sorted(filtered, key=lambda item: (str(item.get("category", "")), str(item.get("relative_path", ""))))
