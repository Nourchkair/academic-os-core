from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
