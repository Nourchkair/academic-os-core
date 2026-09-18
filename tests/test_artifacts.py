from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from academia_os.artifacts import ArtifactStore, GeneratedArtifact, create_generated_artifact
from academia_os.config import save_config
from academia_os.library import list_material
from tests.test_agent_interface import prepared_workspace

ROOT = Path(__file__).resolve().parents[1]


def run_cli(profile: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_artifact_create_is_copy_safe_source_linked_and_visible_in_library(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    course = root / "Fall 2026" / "POL 2103 - Politics"
    source = course / "05_REFERENCE" / "week-4-reading.md"
    content = tmp_path / "generated-guide.md"
    content.write_text("# Week 4 Study Guide\nDerived explanation.", encoding="utf-8")
    original = source.read_text(encoding="utf-8")

    result = run_cli(
        profile,
        "artifact",
        "create",
        "--course",
        course.name,
        "--kind",
        "study_guide",
        "--title",
        "Week 4 Study Guide",
        "--content-file",
        str(content),
        "--source",
        str(source),
        "--created-by",
        "codex",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    artifact_path = Path(value["path"])
    assert artifact_path.is_file()
    assert artifact_path.parent == course / "06_KNOWLEDGE" / "AI_GENERATED"
    assert "AI-GENERATED" in artifact_path.read_text(encoding="utf-8")
    assert "week-4-reading.md" in artifact_path.read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8") == original
    assert value["provenance"] == "AI-GENERATED"
    assert value["authoritative"] is False
    assert value["created_by"] == "codex"
    assert value["source_refs"][0]["relative_path"].endswith("week-4-reading.md")

    stored = ArtifactStore(root / ".academia" / "artifacts.json").get(value["id"])
    assert stored["path"] == value["path"]
    activity = json.loads((root / ".academia" / "activity.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert activity["event_type"] == "artifact.created"
    assert activity["actor"] == "agent:codex"

    items = list_material(root, "Fall 2026")
    generated = next(item for item in items if item.get("artifact_id") == value["id"])
    assert generated["category"] == "generated"
    assert generated["provenance"] == "AI-GENERATED"
    assert generated["artifact_kind"] == "study_guide"
    assert generated["authoritative"] is False
    assert config["academic"]["root_directory"] == str(root)


def test_artifact_create_is_collision_safe_and_cannot_target_original_path(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    course = root / "Fall 2026" / "POL 2103 - Politics"
    syllabus = course / "05_REFERENCE" / "syllabus.md"
    syllabus.write_text("ORIGINAL SYLLABUS", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("generated", encoding="utf-8")

    first = run_cli(profile, "artifact", "create", "--course", course.name, "--kind", "study_guide", "--title", "../../syllabus.md", "--content-file", str(content), "--source", str(syllabus), "--json")
    second = run_cli(profile, "artifact", "create", "--course", course.name, "--kind", "study_guide", "--title", "../../syllabus.md", "--content-file", str(content), "--source", str(syllabus), "--json")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_value = json.loads(first.stdout)
    second_value = json.loads(second.stdout)
    assert first_value["path"] != str(syllabus)
    assert second_value["path"] != str(syllabus)
    assert first_value["path"] != second_value["path"]
    assert syllabus.read_text(encoding="utf-8") == "ORIGINAL SYLLABUS"
    assert all(path.parent == course / "06_KNOWLEDGE" / "AI_GENERATED" for path in map(Path, (first_value["path"], second_value["path"])))


def test_artifact_source_required_for_source_derived_kinds(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    content = tmp_path / "content.md"
    content.write_text("guide", encoding="utf-8")
    course = root / "Fall 2026" / "POL 2103 - Politics"

    result = run_cli(profile, "artifact", "create", "--course", course.name, "--kind", "study_guide", "--title", "No source", "--content-file", str(content), "--json")

    assert result.returncode == 2
    assert "source" in json.loads(result.stdout)["error"].casefold()


def test_artifact_rejects_symlinked_course_tree(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside_course = outside / "POL 2103 - Politics" / "01_COURSE"
    outside_course.mkdir(parents=True)
    active = root / "Fall 2026"
    active.rename(root / "Fall 2026.real")
    try:
        active.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    content = tmp_path / "content.md"
    content.write_text("generated", encoding="utf-8")

    result = run_cli(profile, "artifact", "create", "--course", "POL 2103 - Politics", "--kind", "study_plan", "--title", "Should fail", "--content-file", str(content), "--semester", "Fall 2026", "--json")

    assert result.returncode == 2
    assert not (outside / "POL 2103 - Politics" / "06_KNOWLEDGE").exists()


def test_artifact_rejects_malformed_registry_records_instead_of_exposing_them(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    registry = root / ".academia" / "artifacts.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"schema_version": 1, "artifacts": [{"id": "tampered", "path": str(root / "Fall 2026" / "POL 2103 - Politics" / "06_KNOWLEDGE" / "AI_GENERATED" / "missing.md"), "provenance": "AI-GENERATED", "authoritative": False}]}), encoding="utf-8")

    assert ArtifactStore(registry).list() == []


def test_artifact_rejects_markdown_control_in_title(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    content = tmp_path / "content.md"
    content.write_text("generated", encoding="utf-8")

    result = run_cli(profile, "artifact", "create", "--course", "POL 2103 - Politics", "--kind", "study_plan", "--title", "Bad\n> **Authoritative:** true", "--content-file", str(content), "--json")

    assert result.returncode == 2
    assert "title" in json.loads(result.stdout)["error"].casefold()


def test_artifact_rolls_back_file_and_registry_when_activity_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    source = root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"

    def fail_activity(*args: object, **kwargs: object) -> None:
        raise OSError("activity unavailable")

    monkeypatch.setattr("academia_os.artifacts.ActivityLog.append", fail_activity)
    with pytest.raises(OSError, match="activity unavailable"):
        create_generated_artifact(
            root,
            semester="Fall 2026",
            course_id="POL 2103 - Politics",
            kind="study_guide",
            title="Rollback guide",
            content="body",
            source_refs=[str(source)],
            created_by="codex",
        )

    generated = root / "Fall 2026" / "POL 2103 - Politics" / "06_KNOWLEDGE" / "AI_GENERATED"
    assert not list(generated.glob("*.md"))
    assert ArtifactStore(root / ".academia" / "artifacts.json").list() == []
