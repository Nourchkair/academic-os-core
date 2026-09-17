from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SKIP_DIRECTORY_NAMES = {".git", ".hermes", "Library", "node_modules", "venv", ".venv", "__pycache__"}
ACADEMIC_NAME_HINTS = {"university": 6, "college": 5, "school": 4, "academic": 4, "academics": 5, "coursework": 4, "classes": 3}


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
    return AcademicFolderCandidate(path.resolve(), score, tuple(reasons)) if score else None


def discover_academic_folders(search_roots: Iterable[Path] | None = None, *, max_depth: int = 3) -> list[AcademicFolderCandidate]:
    if search_roots is None:
        base_roots = [Path.home() / name for name in ("Desktop", "Documents", "Downloads", "University", "School", "Academics")]
        possible: set[Path] = set(base_roots)
        for root in base_roots:
            for name in ACADEMIC_NAME_HINTS:
                possible.add(root / name)
                possible.add(root / name / "University")
        ranked = [_folder_score(path) for path in sorted(possible)]
        return sorted((item for item in ranked if item is not None), key=lambda item: (-item.score, str(item.path).lower()))
    candidates: dict[Path, AcademicFolderCandidate] = {}
    for root in search_roots:
        root = Path(root).expanduser()
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
                if candidate is not None and (candidates.get(candidate.path) is None or candidate.score > candidates[candidate.path].score):
                    candidates[candidate.path] = candidate
        except (OSError, ValueError):
            continue
    return sorted(candidates.values(), key=lambda item: (-item.score, str(item.path).lower()))
