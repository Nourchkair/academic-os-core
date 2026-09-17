from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CURRENT_CONFIG_VERSION, load_config, save_config, validate_config, SEMESTER_PATTERN
from .semester import resolve_current_semester

SEMESTER_DIRECTORY = SEMESTER_PATTERN
STANDARD_COURSE_DIRECTORIES = (
    "00_INBOX",
    "01_COURSE",
    "02_WEEKS",
    "03_ASSIGNMENTS",
    "04_EXAMS",
    "05_REFERENCE",
    "06_KNOWLEDGE",
    "99_ARCHIVE",
)
REQUIRED_WORKSPACE_MARKERS = (
    "ACADEMIC_OS_RULES.md",
    "COURSE_TEMPLATE",
)


def _file_count(root: Path) -> int:
    return sum(
        1
        for path in root.rglob("*")
        if path.is_file() and path.name not in {".DS_Store"} and ".academia" not in path.parts
    )


def _course_projection(path: Path) -> dict[str, Any]:
    present = [name for name in STANDARD_COURSE_DIRECTORIES if (path / name).is_dir()]
    missing = [name for name in STANDARD_COURSE_DIRECTORIES if name not in present]
    return {
        "name": path.name,
        "path": str(path),
        "course_code": path.name.split(" - ", 1)[0].strip() if " - " in path.name else "",
        "directories": present,
        "missing_directories": missing,
        "complete_structure": not missing,
        "file_count": _file_count(path),
    }


def _semester_projection(path: Path) -> dict[str, Any]:
    courses = [
        _course_projection(candidate)
        for candidate in sorted(path.iterdir(), key=lambda item: item.name.casefold())
        if candidate.is_dir() and (candidate / "01_COURSE").is_dir()
    ]
    return {
        "name": path.name,
        "path": str(path),
        "courses": courses,
        "course_count": len(courses),
    }


def inspect_workspace(root: Path) -> dict[str, Any]:
    """Build a read-only filesystem projection of an existing academic workspace.

    This function deliberately does not create `.academia/`, indexes, profiles, or
    any other files. It only reads directory names, marker files, and file counts.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace folder does not exist or is not a directory: {root}")

    markers = {
        name: (root / name).is_dir() if name == "COURSE_TEMPLATE" else (root / name).is_file()
        for name in REQUIRED_WORKSPACE_MARKERS
    }
    semesters = [
        _semester_projection(candidate)
        for candidate in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if candidate.is_dir() and SEMESTER_DIRECTORY.fullmatch(candidate.name)
    ]
    anomalies: list[dict[str, str]] = []
    for marker, present in markers.items():
        if not present:
            anomalies.append({"severity": "warning", "path": str(root / marker), "message": f"missing workspace marker: {marker}"})
    if not semesters:
        anomalies.append({"severity": "warning", "path": str(root), "message": "no semester folders matched the expected format"})
    for semester in semesters:
        if not semester["courses"]:
            anomalies.append({"severity": "warning", "path": semester["path"], "message": "semester has no recognized course folders"})
        for course in semester["courses"]:
            if course["missing_directories"]:
                missing = ", ".join(course["missing_directories"])
                anomalies.append({
                    "severity": "warning",
                    "path": course["path"],
                    "message": f"missing course directories: {missing}",
                })

    current = resolve_current_semester()
    semester_names = {item["name"] for item in semesters}
    suggested = current if current in semester_names else (semesters[0]["name"] if semesters else current)
    return {
        "path": str(root),
        "read_only": True,
        "recognized": markers["ACADEMIC_OS_RULES.md"] and markers["COURSE_TEMPLATE"],
        "markers": markers,
        "semesters": semesters,
        "semester_count": len(semesters),
        "course_count": sum(item["course_count"] for item in semesters),
        "file_count": _file_count(root),
        "operational_state_present": (root / ".academia").is_dir(),
        "suggested_semester": suggested,
        "anomalies": anomalies,
    }


def assess_profile(profile_path: Path) -> tuple[str, dict[str, Any] | None]:
    profile_path = Path(profile_path).expanduser().resolve()
    if not profile_path.exists():
        return "missing", None
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return "invalid", None
    raw_text = json.dumps(raw, ensure_ascii=False)
    if "pytest-of-" in raw_text or (
        isinstance(raw.get("student"), dict)
        and raw["student"].get("name") == "Alex Student"
        and raw["student"].get("institution") == "Example University"
    ):
        return "stale_test_data", None
    try:
        normalized = load_config(profile_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "invalid", None
    return "valid", normalized


def _fresh_config(
    *,
    root: Path,
    profile_path: Path,
    name: str,
    institution: str,
    program: str,
    timezone_name: str,
    semester: str,
) -> dict[str, Any]:
    return validate_config(
        {
            "schema_version": CURRENT_CONFIG_VERSION,
            "student": {"name": name, "institution": institution, "program": program},
            "academic": {
                "root_directory": str(root),
                "semester": semester,
                "timezone": timezone_name,
                "school_portal": "Not yet specified",
            },
            "runtime": {"install_directory": str(profile_path.parent)},
        }
    )


def backup_profile(profile_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = profile_path.with_name(f"{profile_path.name}.backup-{stamp}")
    counter = 1
    while candidate.exists():
        candidate = profile_path.with_name(f"{profile_path.name}.backup-{stamp}-{counter}")
        counter += 1
    shutil.copy2(profile_path, candidate)
    return candidate


def attach_workspace(
    root: Path,
    profile_path: Path,
    *,
    name: str,
    institution: str,
    program: str = "",
    timezone: str = "UTC",
    semester: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or explicitly apply a profile attachment without touching academic files."""
    root = Path(root).expanduser().resolve()
    profile_path = Path(profile_path).expanduser().resolve()
    inspection = inspect_workspace(root)
    if not inspection["recognized"]:
        raise ValueError("selected folder is not a recognized Academic OS workspace")
    if not name.strip() or not institution.strip():
        raise ValueError("name and institution are required to attach a workspace")
    selected_semester = semester or str(inspection["suggested_semester"])
    profile_state, existing = assess_profile(profile_path)
    base = copy.deepcopy(existing) if profile_state == "valid" and existing is not None else {}
    candidate = _fresh_config(
        root=root,
        profile_path=profile_path,
        name=name.strip(),
        institution=institution.strip(),
        program=program.strip(),
        timezone_name=timezone,
        semester=selected_semester,
    )
    if base:
        # Preserve non-structural preferences and integration choices from a
        # genuinely valid profile, while explicitly replacing identity/root data.
        for section in ("preferences", "integrations", "automation", "acquisition", "privacy", "browser", "agents"):
            if isinstance(base.get(section), dict):
                candidate[section] = copy.deepcopy(base[section])
        candidate = validate_config(candidate)

    result: dict[str, Any] = {
        "applied": False,
        "requires_confirmation": True,
        "profile_path": str(profile_path),
        "profile_state": profile_state,
        "inspection": inspection,
        "candidate": candidate,
        "academic_files_changed": False,
        "operational_state_created": False,
    }
    if not apply:
        return result

    backup: Path | None = None
    if profile_path.exists():
        backup = backup_profile(profile_path)
    save_config(profile_path, candidate)
    result["applied"] = True
    result["requires_confirmation"] = False
    result["backup_profile"] = str(backup) if backup else None
    return result
