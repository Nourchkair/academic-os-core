from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer.core import (  # noqa: E402
    build_cron_specs,
    initialize_installation,
    load_manifest,
    render_text,
    validate_manifest,
)


def sample_manifest(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "student": {
            "name": "Alex Student",
            "institution": "Example University",
            "program": "History",
        },
        "academic": {
            "semester": "Fall 2026",
            "timezone": "America/New_York",
            "root_directory": str(tmp_path / "University"),
        },
        "preferences": {
            "explanation_style": "detailed",
            "preferred_format": "markdown",
            "use_visuals": True,
            "study_method": "active recall",
        },
        "integrations": {
            "gmail": False,
            "calendar": False,
            "drive": False,
            "school_portal": False,
        },
        "automation": {
            "daily_brief_enabled": True,
            "daily_brief_time": "09:00",
            "inbox_processor_enabled": True,
            "inbox_interval_minutes": 5,
        },
        "browser": {"name": "auto", "user_data_dir": "", "profile_directory": ""},
        "hermes": {
            "home_directory": str(tmp_path / ".hermes"),
            "profile": "default",
            "install_directory": str(tmp_path / ".academic-os"),
        },
    }


def test_render_text_replaces_safe_profile_tokens() -> None:
    text = "Hello {{STUDENT_NAME}} at {{INSTITUTION}} in {{TIMEZONE}}."
    rendered = render_text(
        text,
        {
            "student": {"name": "Alex", "institution": "Example U"},
            "academic": {"timezone": "UTC"},
        },
    )
    assert rendered == "Hello Alex at Example U in UTC."


def test_validate_manifest_rejects_missing_identity() -> None:
    manifest = sample_manifest(Path("/tmp"))
    manifest["student"]["name"] = ""
    with pytest.raises(ValueError, match="student.name"):
        validate_manifest(manifest)


def test_load_manifest_reads_json_and_validates(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = load_manifest(path)
    assert loaded["student"]["name"] == "Alex Student"


def test_initialize_installation_creates_safe_instance(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    template_root = ROOT / "templates" / "University"
    result = initialize_installation(
        manifest,
        template_root=template_root,
        repo_root=ROOT,
        allow_existing=False,
    )
    academic_root = Path(manifest["academic"]["root_directory"])
    install_root = Path(manifest["hermes"]["install_directory"])
    assert result["status"] == "initialized"
    assert (academic_root / "README.md").is_file()
    assert (academic_root / "COURSE_TEMPLATE" / "00_INBOX" / ".gitkeep").is_file()
    assert (academic_root / "Fall 2026" / "SEMESTER_TASKS.md").is_file()
    assert (install_root / "profile.json").is_file()
    assert (install_root / "scripts" / "academic_os_inbox_gate.py").is_file()
    assert "Alex Student" in (academic_root / "README.md").read_text(encoding="utf-8")


def test_initialize_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    academic_root = Path(manifest["academic"]["root_directory"])
    academic_root.mkdir(parents=True)
    (academic_root / "README.md").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(FileExistsError):
        initialize_installation(
            manifest,
            template_root=ROOT / "templates" / "University",
            repo_root=ROOT,
            allow_existing=False,
        )
    assert (academic_root / "README.md").read_text(encoding="utf-8") == "do not overwrite"


def test_invalid_timezone_is_rejected(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    manifest["academic"]["timezone"] = "Toronto"
    with pytest.raises(ValueError, match="valid IANA"):
        validate_manifest(manifest)


def test_cron_specs_are_local_and_do_not_use_messaging_destinations(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    specs = build_cron_specs(manifest)
    assert {spec["name"] for spec in specs} == {
        "Academic OS — Daily Brief",
        "Academic OS — Inbox Processor",
    }
    for spec in specs:
        assert spec["workdir"] == manifest["academic"]["root_directory"]
        assert spec["deliver"] == "local"
        assert "chat_id" not in json.dumps(spec)
        assert "telegram" not in json.dumps(spec).lower()
    inbox = next(spec for spec in specs if spec["name"].endswith("Inbox Processor"))
    assert inbox["script"] == "academic_os_inbox_gate.py"


def test_hermes_free_installation_only_copies_neutral_runtime(tmp_path: Path) -> None:
    manifest = sample_manifest(tmp_path)
    manifest.pop("hermes", None)
    manifest["schema_version"] = 2
    manifest["runtime"] = {"install_directory": str(tmp_path / ".academic-os")}
    manifest["agents"] = {"hermes": {"enabled": False, "profile": "default"}}
    result = initialize_installation(
        manifest,
        template_root=ROOT / "templates" / "University",
        repo_root=ROOT,
    )
    scripts = sorted(path.name for path in (Path(result["install_root"]) / "scripts").glob("*.py"))
    assert scripts == ["academic_os_inbox_gate.py"]
    assert not (Path(result["install_root"]) / "scripts" / "academic_os_brightspace_handoff.py").exists()
