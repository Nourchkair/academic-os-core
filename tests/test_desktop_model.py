from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop.model import (  # noqa: E402
    create_course_from_template,
    detect_local_timezone,
    discover_academic_folders,
    friendly_timezone_choices,
    friendly_timezone_label,
    load_dashboard,
    semester_suggestions,
    timezone_from_friendly_label,
)
from installer.core import initialize_installation  # noqa: E402
from tests.test_installer import sample_manifest  # noqa: E402


def test_discover_academic_folders_ranks_existing_academic_structure(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    candidate = desktop / "University"
    (candidate / "COURSE_TEMPLATE").mkdir(parents=True)
    (candidate / "ACADEMIC_OS_RULES.md").write_text("rules", encoding="utf-8")
    distractor = desktop / "University Photos"
    distractor.mkdir()
    results = discover_academic_folders([desktop], max_depth=2)
    assert results
    assert results[0].path == candidate
    assert results[0].score > results[-1].score
    assert any("Academic OS rules" in reason for reason in results[0].reasons)


def test_discover_academic_folders_does_not_scan_hidden_or_dependency_trees(tmp_path: Path) -> None:
    root = tmp_path / "Desktop"
    hidden = root / ".hidden" / "University"
    dependencies = root / "Project" / "node_modules" / "University"
    hidden.mkdir(parents=True)
    dependencies.mkdir(parents=True)
    assert discover_academic_folders([root], max_depth=4) == []


def test_detect_local_timezone_from_zoneinfo_symlink(tmp_path: Path) -> None:
    zoneinfo = tmp_path / "zoneinfo" / "America" / "New_York"
    zoneinfo.parent.mkdir(parents=True)
    zoneinfo.write_text("placeholder", encoding="utf-8")
    localtime = tmp_path / "localtime"
    localtime.symlink_to(zoneinfo)
    assert detect_local_timezone(localtime) == "America/New_York"


def test_friendly_time_zone_choices_round_trip_to_iana_names() -> None:
    label = friendly_timezone_label("America/Toronto")
    assert "Toronto" in label
    assert timezone_from_friendly_label(label) == "America/Toronto"
    assert friendly_timezone_choices()


def test_semester_suggestions_include_current_year_and_friendly_labels() -> None:
    suggestions = semester_suggestions()
    assert suggestions
    assert any("Current" in item for item in suggestions)
    assert any(item.startswith(("Fall ", "Winter ", "Spring ", "Summer ")) for item in suggestions)


def test_create_course_from_template_is_non_destructive(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    initialize_installation(
        manifest,
        template_root=ROOT / "templates" / "University",
        repo_root=ROOT,
        allow_existing=False,
    )
    root = Path(manifest["academic"]["root_directory"])
    course = create_course_from_template(root, "Fall 2026", "HIS 101", "World History", root / "COURSE_TEMPLATE", manifest)
    assert course.is_dir()
    assert (course / "00_INBOX" / ".gitkeep").is_file()
    with pytest.raises(FileExistsError):
        create_course_from_template(root, "Fall 2026", "HIS 101", "World History", root / "COURSE_TEMPLATE", manifest)


def test_attach_existing_root_preserves_custom_files(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    root = Path(manifest["academic"]["root_directory"])
    root.mkdir(parents=True)
    (root / "ACADEMIC_OS_RULES.md").write_text("custom rules", encoding="utf-8")
    (root / "COURSE_TEMPLATE").mkdir()
    initialize_installation(
        manifest,
        template_root=ROOT / "templates" / "University",
        repo_root=ROOT,
        attach_existing=True,
    )
    assert (root / "ACADEMIC_OS_RULES.md").read_text(encoding="utf-8") == "custom rules"
    assert (Path(manifest["runtime"]["install_directory"]) / "profile.json").is_file()


def test_load_dashboard_reports_empty_and_configured_state(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    initialize_installation(
        manifest,
        template_root=ROOT / "templates" / "University",
        repo_root=ROOT,
        allow_existing=False,
    )
    profile = Path(manifest["runtime"]["install_directory"]) / "profile.json"
    dashboard = load_dashboard(profile)
    assert dashboard["student_name"] == "Alex Student"
    assert dashboard["course_count"] == 0
    assert dashboard["inbox_count"] == 0
