from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer import migration  # noqa: E402
from installer.migration import build_migration_plan, execute_migration_plan, write_migration_plan  # noqa: E402


def test_migration_plan_preserves_relative_paths_and_routes_unknowns_to_inbox(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    new_root = tmp_path / "New University"
    (source / "Fall 2024" / "HIS 101").mkdir(parents=True)
    (source / "Fall 2026" / "Current Course").mkdir(parents=True)
    (source / "Loose Files").mkdir()
    (source / ".hidden").mkdir()
    (source / "Fall 2024" / "HIS 101" / "essay.pdf").write_bytes(b"essay")
    (source / "Fall 2026" / "Current Course" / "syllabus.docx").write_bytes(b"syllabus")
    (source / "Loose Files" / "notes.txt").write_bytes(b"notes")
    (source / ".DS_Store").write_bytes(b"ignore")
    (source / "partial.crdownload").write_bytes(b"ignore")

    plan = build_migration_plan(source, new_root, "Fall 2026")
    assert len(plan.items) == 3
    destinations = {item.destination.relative_to(new_root).as_posix() for item in plan.items}
    assert "Fall 2024/99_ARCHIVE/LEGACY_IMPORT/Old University/Fall 2024/HIS 101/essay.pdf" in destinations
    assert "Fall 2026/00_INBOX/LEGACY_IMPORT/Old University/Fall 2026/Current Course/syllabus.docx" in destinations
    assert "Fall 2026/00_INBOX/LEGACY_IMPORT/Old University/Loose Files/notes.txt" in destinations


def test_copy_is_default_and_move_removes_only_verified_source(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    new_root = tmp_path / "New University"
    source.mkdir()
    document = source / "notes.md"
    document.write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, new_root, "Current Semester")

    copy_result = execute_migration_plan(plan, items=plan.items, mode="copy")
    assert copy_result["copied"] == 1
    assert document.is_file()
    destination = plan.items[0].destination
    assert destination.read_text(encoding="utf-8") == "notes"

    move_source = source / "todo.txt"
    move_source.write_text("todo", encoding="utf-8")
    move_plan = build_migration_plan(source, new_root, "Current Semester")
    move_item = next(item for item in move_plan.items if item.source == move_source)
    move_result = execute_migration_plan(move_plan, items=[move_item], mode="move")
    assert move_result["moved"] == 1
    assert not move_source.exists()
    assert move_item.destination.read_text(encoding="utf-8") == "todo"


def test_collision_never_overwrites_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    new_root = tmp_path / "New University"
    source.mkdir()
    document = source / "notes.md"
    document.write_text("new source", encoding="utf-8")
    plan = build_migration_plan(source, new_root, "Current Semester")
    plan.items[0].destination.parent.mkdir(parents=True)
    plan.items[0].destination.write_text("existing", encoding="utf-8")

    result = execute_migration_plan(plan, items=plan.items, mode="copy")
    assert result["copied"] == 1
    assert plan.items[0].destination.read_text(encoding="utf-8") == "existing"
    collision = result["destinations"][0]
    assert collision != str(plan.items[0].destination)
    assert Path(collision).read_text(encoding="utf-8") == "new source"


def test_migration_plan_writes_ai_reviewable_json_and_markdown(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    paths = write_migration_plan(plan, tmp_path / "migration")
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    assert "Do not move files directly" in paths["markdown"].read_text(encoding="utf-8")


def test_write_migration_plan_keeps_untrusted_markdown_labels_on_one_line(tmp_path: Path) -> None:
    source = tmp_path / ("Old `University" + chr(10) + "- injected")
    academic_root = tmp_path / ("New `Academic" + chr(10) + "Root")
    source.mkdir()
    (source / ("notes`review" + chr(10) + "- injected.txt")).write_text("notes", encoding="utf-8")

    plan = build_migration_plan(source, academic_root, "Fall 2026")
    markdown = write_migration_plan(plan, tmp_path / "migration")["markdown"].read_text(encoding="utf-8")

    source_line = next(line for line in markdown.splitlines() if line.startswith("- Source:"))
    academic_line = next(line for line in markdown.splitlines() if line.startswith("- New Academic OS root:"))
    item_line = next(line for line in markdown.splitlines() if line.startswith("- ``notes"))
    assert source_line.startswith("- Source: ``") and source_line.endswith("``")
    assert academic_line.startswith("- New Academic OS root: ``") and academic_line.endswith("``")
    assert item_line.startswith("- ``") and "→ ``" in item_line
    assert "\\n- injected" in source_line
    assert "\\n- injected" in item_line
    assert "\n- injected" not in markdown


def test_load_migration_plan_reconstructs_and_validates_persisted_paths(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    academic_root = tmp_path / "New University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, academic_root, "Fall 2026")
    plan_path = write_migration_plan(plan, tmp_path / "migration")["json"]

    restored = migration.load_migration_plan(plan_path)

    assert restored == plan

    malformed = plan.as_json()
    malformed["items"][0]["relative_path"] = "../escape.txt"
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="relative path"):
        migration.load_migration_plan(plan_path)

    malformed = plan.as_json()
    malformed["items"][0]["source"] = str(tmp_path / "outside.txt")
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        migration.load_migration_plan(plan_path)

    malformed = plan.as_json()
    malformed["items"][0]["destination"] = str(tmp_path / "outside-destination.txt")
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="destination"):
        migration.load_migration_plan(plan_path)


def test_load_migration_plan_rejects_malformed_version_and_operational_source_root(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    plan_path = write_migration_plan(plan, tmp_path / "migration")["json"]

    malformed = plan.as_json()
    malformed["version"] = 99
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        migration.load_migration_plan(plan_path)

    operational = tmp_path / ".academia"
    operational.mkdir()
    (operational / "processing.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="operational"):
        build_migration_plan(operational, tmp_path / "Another University", "Fall 2026")


def test_write_migration_plan_rejects_symlinked_plan_target(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    directory = tmp_path / "migration"
    directory.mkdir()
    protected = tmp_path / "protected-plan.json"
    protected.write_text("keep plan target", encoding="utf-8")
    plan_path = directory / "migration-plan.json"
    plan_path.symlink_to(protected)

    with pytest.raises(ValueError, match="symlink"):
        write_migration_plan(plan, directory)

    assert plan_path.is_symlink()
    assert protected.read_text(encoding="utf-8") == "keep plan target"


def test_write_migration_plan_rejects_symlinked_review_target(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    directory = tmp_path / "migration"
    paths = write_migration_plan(plan, directory)
    protected = tmp_path / "protected-review.md"
    protected.write_text("keep review target", encoding="utf-8")
    paths["markdown"].unlink()
    paths["markdown"].symlink_to(protected)

    with pytest.raises(ValueError, match="symlink"):
        write_migration_plan(plan, directory)

    assert paths["markdown"].is_symlink()
    assert protected.read_text(encoding="utf-8") == "keep review target"


def test_write_migration_plan_validates_before_creating_outputs(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    malformed = migration.MigrationPlan(
        source_root=plan.source_root,
        academic_root=plan.academic_root,
        current_semester="not a semester",
        items=plan.items,
        created_at=plan.created_at,
    )
    directory = tmp_path / "migration"

    with pytest.raises(ValueError, match="current_semester"):
        write_migration_plan(malformed, directory)

    assert not directory.exists()


def test_write_migration_plan_clears_stale_report_only_for_new_valid_plan(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    directory = tmp_path / "migration"
    paths = write_migration_plan(plan, directory)
    report_path = directory / "migration-report.json"
    report_path.write_text('{"status": "old"}\n', encoding="utf-8")

    write_migration_plan(plan, directory)

    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    assert not report_path.exists()


def test_write_migration_plan_rejects_symlinked_output_directory(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    real_directory = tmp_path / "real-migration"
    real_directory.mkdir()
    directory = tmp_path / "migration"
    directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        write_migration_plan(plan, directory)

    assert not (real_directory / "migration-plan.json").exists()
    assert not (real_directory / "MIGRATION_REVIEW.md").exists()


def test_write_migration_plan_preflights_report_directory_before_writing_plan(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    directory = tmp_path / "migration"
    paths = write_migration_plan(plan, directory)
    original_plan = paths["json"].read_text(encoding="utf-8")
    report_path = directory / "migration-report.json"
    report_path.mkdir()

    with pytest.raises(ValueError, match="directory"):
        write_migration_plan(plan, directory)

    assert paths["json"].read_text(encoding="utf-8") == original_plan
    assert report_path.is_dir()


def test_load_migration_plan_rejects_operational_academic_roots(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()

    for directory_name in (".academia", ".academic-os", ".hermes"):
        plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
        plan_path = write_migration_plan(plan, tmp_path / f"migration-{directory_name[1:]}")["json"]
        malformed = plan.as_json()
        malformed["academic_root"] = str(tmp_path / directory_name / "New University")
        plan_path.write_text(json.dumps(malformed), encoding="utf-8")

        with pytest.raises(ValueError, match="academic root.*operational"):
            migration.load_migration_plan(plan_path)


def test_load_migration_plan_rejects_missing_or_non_directory_source_root(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()
    plan = build_migration_plan(source, tmp_path / "New University", "Fall 2026")
    plan_path = write_migration_plan(plan, tmp_path / "migration")["json"]
    non_directory = tmp_path / "source-file"
    non_directory.write_text("not a directory", encoding="utf-8")

    for source_root in (tmp_path / "missing-source", non_directory):
        malformed = plan.as_json()
        malformed["source_root"] = str(source_root)
        plan_path.write_text(json.dumps(malformed), encoding="utf-8")

        with pytest.raises(ValueError, match="source root.*folder"):
            migration.load_migration_plan(plan_path)


def test_build_migration_plan_rejects_operational_academic_root(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    source.mkdir()

    for directory_name in (".academia", ".academic-os", ".hermes"):
        with pytest.raises(ValueError, match="academic root.*operational"):
            build_migration_plan(source, tmp_path / directory_name / "New University", "Fall 2026")


def test_load_migration_plan_requires_disjoint_roots_and_strict_item_descendants(tmp_path: Path) -> None:
    source_root = tmp_path / "container"
    academic_root = source_root / "active-workspace"
    source_root.mkdir()
    academic_root.mkdir()
    victim = academic_root / "active.txt"
    victim.write_text("active", encoding="utf-8")
    destination = academic_root / "Fall 2026" / "00_INBOX" / "LEGACY_IMPORT" / "active.txt"
    plan_path = tmp_path / "crafted-plan.json"

    crafted = {
        "version": migration.PLAN_VERSION,
        "source_root": str(source_root),
        "academic_root": str(academic_root),
        "current_semester": "Fall 2026",
        "created_at": "2026-09-17T12:00:00+00:00",
        "item_count": 1,
        "total_size": victim.stat().st_size,
        "items": [
            {
                "source": str(victim),
                "destination": str(destination),
                "relative_path": "active-workspace/active.txt",
                "semester": "Fall 2026",
                "size": victim.stat().st_size,
                "sha256": migration.sha256_file(victim),
            }
        ],
    }
    plan_path.write_text(json.dumps(crafted), encoding="utf-8")

    with pytest.raises(ValueError, match="disjoint"):
        migration.load_migration_plan(plan_path)

    distinct_source = tmp_path / "Old University"
    distinct_academic = tmp_path / "New University"
    distinct_source.mkdir()
    source_item = distinct_source / "notes.txt"
    source_item.write_text("notes", encoding="utf-8")
    valid_plan = build_migration_plan(distinct_source, distinct_academic, "Fall 2026")
    malformed = valid_plan.as_json()
    malformed["items"][0]["source"] = str(distinct_source)
    malformed["items"][0]["relative_path"] = "notes.txt"
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match="strict descendant"):
        migration.load_migration_plan(plan_path)

    malformed = valid_plan.as_json()
    malformed["items"][0]["destination"] = str(distinct_academic)
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match="strict descendant"):
        migration.load_migration_plan(plan_path)


def test_source_symlink_is_not_planned_and_persisted_source_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    academic_root = tmp_path / "New University"
    source.mkdir()
    target = source / "protected.txt"
    target.write_text("protected", encoding="utf-8")
    source_link = source / "linked.txt"
    source_link.symlink_to(target)

    plan = build_migration_plan(source, academic_root, "Fall 2026")
    assert all(item.source != source_link for item in plan.items)

    regular = source / "regular.txt"
    regular.write_text("regular", encoding="utf-8")
    plan = build_migration_plan(source, academic_root, "Fall 2026")
    plan_path = write_migration_plan(plan, tmp_path / "migration")["json"]
    malformed = plan.as_json()
    malformed["items"][0]["source"] = str(source_link)
    malformed["items"][0]["relative_path"] = "protected.txt"
    malformed["items"][0]["size"] = target.stat().st_size
    malformed["items"][0]["sha256"] = migration.sha256_file(target)
    malformed["total_size"] = sum(item["size"] for item in malformed["items"])
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match="symlink"):
        migration.load_migration_plan(plan_path)
    assert target.read_text(encoding="utf-8") == "protected"


def test_execute_rejects_destination_parent_symlink_before_copy(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    academic_root = tmp_path / "New University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, academic_root, "Fall 2026")
    outside = tmp_path / "outside"
    outside.mkdir()
    academic_root.mkdir()
    (academic_root / "Fall 2026").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        execute_migration_plan(plan, mode="copy")

    assert document.read_text(encoding="utf-8") == "notes"
    assert not (outside / "00_INBOX").exists()


def test_execute_rejects_selected_item_not_in_plan_and_revalidates_containment(tmp_path: Path) -> None:
    source = tmp_path / "Old University"
    academic_root = tmp_path / "New University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    plan = build_migration_plan(source, academic_root, "Fall 2026")

    foreign_source = tmp_path / "Foreign University"
    foreign_source.mkdir()
    foreign_document = foreign_source / "foreign.txt"
    foreign_document.write_text("foreign", encoding="utf-8")
    foreign_plan = build_migration_plan(foreign_source, tmp_path / "Foreign New University", "Fall 2026")

    with pytest.raises(ValueError, match="not part of"):
        execute_migration_plan(plan, items=foreign_plan.items)
    assert document.is_file()
    assert foreign_document.is_file()

    unsafe_item = migration.MigrationItem(
        source=academic_root / "active.txt",
        destination=plan.items[0].destination,
        relative_path="active.txt",
        semester=plan.items[0].semester,
        size=plan.items[0].size,
        sha256=plan.items[0].sha256,
    )
    unsafe_plan = migration.MigrationPlan(
        source_root=tmp_path,
        academic_root=academic_root,
        current_semester=plan.current_semester,
        items=(unsafe_item,),
        created_at=plan.created_at,
    )

    with pytest.raises(ValueError, match="source"):
        execute_migration_plan(unsafe_plan)
    assert document.is_file()


def test_execute_rejects_dot_symlink_traversal_in_direct_item_path(tmp_path: Path) -> None:
    source_root = tmp_path / "Old University"
    academic_root = tmp_path / "New University"
    outside = tmp_path / "outside"
    source_root.mkdir()
    outside.mkdir()
    (source_root / "victim.txt").write_text("inside", encoding="utf-8")
    outside_victim = outside / "victim.txt"
    outside_victim.write_text("outside", encoding="utf-8")
    (source_root / "link").symlink_to(outside, target_is_directory=True)
    destination = academic_root / "Fall 2026" / "00_INBOX" / "LEGACY_IMPORT" / source_root.name / "victim.txt"

    item = migration.MigrationItem(
        source=source_root / "link" / ".." / "victim.txt",
        destination=destination,
        relative_path="victim.txt",
        semester="Fall 2026",
        size=outside_victim.stat().st_size,
        sha256=migration.sha256_file(outside_victim),
    )
    plan = migration.MigrationPlan(
        source_root=source_root,
        academic_root=academic_root,
        current_semester="Fall 2026",
        items=(item,),
        created_at="2026-09-17T12:00:00+00:00",
    )

    with pytest.raises(ValueError, match="symlink|traversal|normalized|dot"):
        execute_migration_plan(plan)
    assert not academic_root.exists()
    assert (source_root / "victim.txt").read_text(encoding="utf-8") == "inside"


def test_build_rejects_case_alias_root_overlap_when_samefile_supported(tmp_path: Path) -> None:
    source_root = tmp_path / "Old University"
    source_root.mkdir()
    case_alias = tmp_path / "old university"
    try:
        same_directory = os.path.samefile(source_root, case_alias)
    except FileNotFoundError:
        pytest.skip("filesystem is case-sensitive")
    if not same_directory:
        pytest.skip("filesystem is case-sensitive")

    with pytest.raises(ValueError, match="disjoint|different"):
        build_migration_plan(source_root, case_alias / "New University", "Fall 2026")
