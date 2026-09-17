from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import available_timezones

from installer.core import _copy_tree, validate_manifest

SKIP_DIRECTORY_NAMES = {".git", ".hermes", "Library", "node_modules", "venv", ".venv", "__pycache__"}
ACADEMIC_NAME_HINTS = {
    "university": 6,
    "college": 5,
    "school": 4,
    "academic": 4,
    "academics": 5,
    "coursework": 4,
    "classes": 3,
}
COMMON_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Toronto",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Vancouver",
    "America/Edmonton",
    "America/Halifax",
    "America/St_Johns",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
]
FRIENDLY_TIMEZONES = {
    "UTC": "UTC (Coordinated Universal Time)",
    "America/New_York": "Eastern Time — New York / Toronto",
    "America/Toronto": "Eastern Time — Toronto",
    "America/Chicago": "Central Time — Chicago",
    "America/Denver": "Mountain Time — Denver",
    "America/Los_Angeles": "Pacific Time — Los Angeles / Vancouver",
    "America/Vancouver": "Pacific Time — Vancouver",
    "America/Edmonton": "Mountain Time — Edmonton",
    "America/Halifax": "Atlantic Time — Halifax",
    "America/St_Johns": "Newfoundland Time — St. John's",
    "Europe/London": "United Kingdom / Ireland — London",
    "Europe/Paris": "Central Europe — Paris / Berlin",
    "Europe/Berlin": "Central Europe — Berlin",
    "Asia/Dubai": "Gulf Time — Dubai",
    "Asia/Kolkata": "India — Kolkata",
    "Asia/Singapore": "Singapore / Malaysia",
    "Asia/Tokyo": "Japan — Tokyo",
    "Australia/Sydney": "Australia East — Sydney",
}


@dataclass(frozen=True)
class AcademicFolderCandidate:
    path: Path
    score: int
    reasons: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.path} — {', '.join(self.reasons)}"


def _is_hidden_or_skipped(path: Path) -> bool:
    return any(part.startswith(".") or part in SKIP_DIRECTORY_NAMES for part in path.parts)


def _folder_score(path: Path) -> AcademicFolderCandidate | None:
    if not path.is_dir() or _is_hidden_or_skipped(path):
        return None
    score = 0
    reasons: list[str] = []
    lower_name = path.name.lower()
    for hint, points in ACADEMIC_NAME_HINTS.items():
        if hint in lower_name:
            score += points
            reasons.append(f"name matches {hint}")
    if (path / "ACADEMIC_OS_RULES.md").is_file():
        score += 12
        reasons.append("Academic OS rules")
    if (path / "COURSE_TEMPLATE").is_dir():
        score += 10
        reasons.append("course template")
    if score == 0:
        return None
    return AcademicFolderCandidate(path.resolve(), score, tuple(reasons))


def discover_academic_folders(search_roots: Iterable[Path] | None = None, *, max_depth: int = 3) -> list[AcademicFolderCandidate]:
    if search_roots is None:
        base_roots = [Path.home() / name for name in ("Desktop", "Documents", "Downloads", "University", "School", "Academics")]
        names = tuple(ACADEMIC_NAME_HINTS)
        possible: set[Path] = set(base_roots)
        for root in base_roots:
            for name in names:
                possible.add(root / name)
                possible.add(root / name / "University")
        ranked = [_folder_score(path) for path in sorted(possible)]
        return sorted((item for item in ranked if item is not None), key=lambda item: (-item.score, str(item.path).lower()))

    roots = list(search_roots)
    candidates: dict[Path, AcademicFolderCandidate] = {}
    for root in roots:
        root = root.expanduser()
        if not root.is_dir():
            continue
        try:
            for current, directories, _files in os.walk(root):
                current_path = Path(current)
                relative_depth = len(current_path.relative_to(root).parts)
                if relative_depth > max_depth:
                    directories[:] = []
                    continue
                directories[:] = [name for name in directories if not name.startswith(".") and name not in SKIP_DIRECTORY_NAMES]
                candidate = _folder_score(current_path)
                if candidate is not None:
                    existing = candidates.get(candidate.path)
                    if existing is None or candidate.score > existing.score:
                        candidates[candidate.path] = candidate
        except (OSError, ValueError):
            continue
    return sorted(candidates.values(), key=lambda item: (-item.score, str(item.path).lower()))


def detect_local_timezone(localtime_path: Path | None = None) -> str:
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz and env_tz in available_timezones():
        return env_tz
    localtime = (localtime_path or Path("/etc/localtime")).expanduser()
    try:
        resolved = localtime.resolve()
        parts = resolved.parts
        if "zoneinfo" in parts:
            index = parts.index("zoneinfo")
            candidate = "/".join(parts[index + 1 :])
            if candidate in available_timezones():
                return candidate
    except OSError:
        pass
    return ""


def timezone_choices(filter_text: str = "") -> list[str]:
    query = filter_text.strip().lower()
    values = sorted(available_timezones())
    if not query:
        preferred = [item for item in COMMON_TIMEZONES if item in values]
        return preferred + [item for item in values if item not in preferred]
    return [item for item in values if query in item.lower()]


def friendly_timezone_label(timezone_name: str) -> str:
    return FRIENDLY_TIMEZONES.get(timezone_name, timezone_name)


def friendly_timezone_choices() -> list[str]:
    values = [friendly_timezone_label(item) for item in COMMON_TIMEZONES if item in available_timezones()]
    return values + ["Other time zone…"]


def timezone_from_friendly_label(label: str) -> str:
    for timezone_name, friendly in FRIENDLY_TIMEZONES.items():
        if label == friendly:
            return timezone_name
    return label.strip()


def semester_suggestions(now: datetime | None = None) -> list[str]:
    current = now or datetime.now()
    year = current.year
    return [
        "Current Semester",
        f"Fall {year}",
        f"Winter {year}",
        f"Spring {year}",
        f"Summer {year}",
        f"Fall {year + 1}",
        f"Winter {year + 1}",
    ]


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
    destination = academic_root.expanduser() / semester.strip() / f"{code} - {title}"
    if destination.exists():
        raise FileExistsError(f"course folder already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(template_root, destination, manifest, allow_existing=False)
    return destination


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dashboard(profile_path: Path) -> dict[str, Any]:
    profile = _read_json(profile_path.expanduser().resolve())
    validate_manifest(profile)
    academic_root = Path(profile["academic"]["root_directory"]).expanduser().resolve()
    semester = str(profile["academic"]["semester"])
    semester_root = academic_root / semester
    courses = []
    inbox_count = 0
    if semester_root.is_dir():
        for candidate in sorted(semester_root.iterdir()):
            if not candidate.is_dir() or not (candidate / "01_COURSE").is_dir():
                continue
            courses.append(candidate.name)
            inbox = candidate / "00_INBOX"
            if inbox.is_dir():
                inbox_count += sum(1 for path in inbox.rglob("*") if path.is_file() and path.name not in {".gitkeep", ".DS_Store"})
    today = semester_root / "TODAY.md"
    today_preview = ""
    if today.is_file():
        lines = [line.strip() for line in today.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        today_preview = "\n".join(lines[:8])
    return {
        "student_name": str(profile["student"]["name"]),
        "institution": str(profile["student"]["institution"]),
        "program": str(profile["student"].get("program", "")),
        "semester": semester,
        "timezone": str(profile["academic"]["timezone"]),
        "academic_root": str(academic_root),
        "install_root": str(Path(profile["hermes"]["install_directory"]).expanduser().resolve()),
        "course_count": len(courses),
        "courses": courses,
        "inbox_count": inbox_count,
        "today_preview": today_preview,
        "root_exists": academic_root.is_dir(),
        "semester_exists": semester_root.is_dir(),
        "integrations": profile.get("integrations", {}),
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
