from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from academia_os.attachment import attach_workspace, inspect_workspace


STANDARD_COURSE_DIRS = (
    "00_INBOX",
    "01_COURSE",
    "02_WEEKS",
    "03_ASSIGNMENTS",
    "04_EXAMS",
    "05_REFERENCE",
    "06_KNOWLEDGE",
    "99_ARCHIVE",
)


def _hash_tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _populated_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "University"
    root.mkdir()
    (root / "README.md").write_text("workspace", encoding="utf-8")
    (root / "ACADEMIC_OS_RULES.md").write_text("rules", encoding="utf-8")
    (root / "COURSE_TEMPLATE").mkdir()
    (root / "INTEGRATION_STATUS.md").write_text("status", encoding="utf-8")
    semester = root / "Fall 2026"
    course = semester / "HIS 101 - History"
    for directory in STANDARD_COURSE_DIRS:
        (course / directory).mkdir(parents=True)
    (course / "01_COURSE" / "Course_Status.md").write_text("- [ ] Read syllabus\n", encoding="utf-8")
    (semester / "SEMESTER_STATUS.md").write_text("semester", encoding="utf-8")
    (root / "Fall 2025" / "POL 100 - Politics" / "01_COURSE").mkdir(parents=True)
    return root


def test_inspect_populated_workspace_is_read_only_and_projects_courses(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    before = _hash_tree(root)

    inspection = inspect_workspace(root)

    assert inspection["recognized"] is True
    assert inspection["read_only"] is True
    assert inspection["course_count"] == 2
    assert {semester["name"] for semester in inspection["semesters"]} == {"Fall 2025", "Fall 2026"}
    current = next(item for item in inspection["semesters"] if item["name"] == "Fall 2026")
    assert current["courses"][0]["name"] == "HIS 101 - History"
    assert current["courses"][0]["complete_structure"] is True
    assert not (root / ".academia").exists()
    assert _hash_tree(root) == before


def test_inspect_surfaces_structure_anomalies_without_modifying_files(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    incomplete = root / "Fall 2026" / "BIO 101 - Biology"
    (incomplete / "01_COURSE").mkdir(parents=True)
    before = _hash_tree(root)

    inspection = inspect_workspace(root)

    anomalies = inspection["anomalies"]
    assert any("BIO 101 - Biology" in item["path"] and "missing course directories" in item["message"] for item in anomalies)
    assert _hash_tree(root) == before
    assert not (root / ".academia").exists()


def test_attach_preview_does_not_write_profile_or_academic_state(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    profile = tmp_path / ".academic-os" / "profile.json"
    before = _hash_tree(root)

    result = attach_workspace(
        root,
        profile,
        name="Nour Student",
        institution="Example University",
        program="History",
        timezone="America/Toronto",
        semester="Fall 2026",
        apply=False,
    )

    assert result["applied"] is False
    assert result["requires_confirmation"] is True
    assert result["inspection"]["course_count"] == 2
    assert result["candidate"]["academic"]["root_directory"] == str(root)
    assert not profile.exists()
    assert not (root / ".academia").exists()
    assert _hash_tree(root) == before


def test_attach_apply_backs_up_stale_profile_and_preserves_workspace(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    profile = tmp_path / ".academic-os" / "profile.json"
    profile.parent.mkdir()
    stale = {
        "schema_version": 2,
        "student": {"name": "Alex Student", "institution": "Example University", "program": "History"},
        "academic": {"root_directory": str(tmp_path / "pytest-of-nourchkair"), "semester": "Fall 2026", "timezone": "UTC"},
    }
    profile.write_text(json.dumps(stale), encoding="utf-8")
    before = _hash_tree(root)

    result = attach_workspace(
        root,
        profile,
        name="Nour Student",
        institution="Example University",
        program="History",
        timezone="America/Toronto",
        semester="Fall 2026",
        apply=True,
    )

    assert result["applied"] is True
    assert result["profile_state"] == "stale_test_data"
    backup = Path(result["backup_profile"])
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8"))["student"]["name"] == "Alex Student"
    saved = json.loads(profile.read_text(encoding="utf-8"))
    assert saved["academic"]["root_directory"] == str(root)
    assert saved["student"]["name"] == "Nour Student"
    assert not (root / ".academia").exists()
    assert _hash_tree(root) == before


def test_attach_rejects_unrecognized_nonempty_folder(tmp_path: Path) -> None:
    root = tmp_path / "Not University"
    root.mkdir()
    (root / "notes.txt").write_text("private", encoding="utf-8")

    with pytest.raises(ValueError, match="recognized Academic OS workspace"):
        attach_workspace(
            root,
            tmp_path / ".academic-os" / "profile.json",
            name="Nour Student",
            institution="Example University",
            timezone="America/Toronto",
            semester="Fall 2026",
            apply=False,
        )
