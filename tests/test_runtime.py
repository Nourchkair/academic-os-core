from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_profile(tmp_path: Path) -> Path:
    profile = {
        "schema_version": 1,
        "academic": {"root_directory": str(tmp_path / "University")},
        "hermes": {"install_directory": str(tmp_path / ".academic-os"), "home_directory": str(tmp_path / ".hermes")},
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_inbox_gate_ignores_course_template_and_reports_new_file(tmp_path: Path) -> None:
    gate = load_module("runtime/scripts/academic_os_inbox_gate.py", "academic_os_inbox_gate_test")
    root = tmp_path / "University"
    (root / "COURSE_TEMPLATE" / "00_INBOX").mkdir(parents=True)
    (root / "COURSE_TEMPLATE" / "01_COURSE").mkdir()
    course = root / "Fall 2026" / "HIS 101 - History"
    (course / "00_INBOX").mkdir(parents=True)
    (course / "01_COURSE").mkdir()
    (course / "00_INBOX" / "syllabus.pdf").write_bytes(b"x")
    config = write_profile(tmp_path)
    first = gate.scan(config)
    assert first["wakeAgent"] is True
    assert str(course / "00_INBOX" / "syllabus.pdf") in json.dumps(first)
    assert "COURSE_TEMPLATE" not in json.dumps(first)
    second = gate.scan(config)
    assert second == {"wakeAgent": False}


def test_inbox_gate_reports_changed_file(tmp_path: Path) -> None:
    gate = load_module("runtime/scripts/academic_os_inbox_gate.py", "academic_os_inbox_gate_changed_test")
    root = tmp_path / "University"
    course = root / "Fall 2026" / "HIS 101"
    (course / "00_INBOX").mkdir(parents=True)
    (course / "01_COURSE").mkdir()
    item = course / "00_INBOX" / "notes.md"
    item.write_text("one", encoding="utf-8")
    config = write_profile(tmp_path)
    gate.scan(config)
    item.write_text("two", encoding="utf-8")
    changed = gate.scan(config)
    assert changed["wakeAgent"] is True
    assert changed["changed_file_count"] == 1


def test_handoff_filters_and_collision_names(tmp_path: Path) -> None:
    handoff = load_module("runtime/scripts/academic_os_brightspace_handoff.py", "academic_os_handoff_test")
    supported = tmp_path / "lecture.pdf"
    supported.write_bytes(b"lecture")
    temporary = tmp_path / "partial.crdownload"
    temporary.write_bytes(b"partial")
    assert handoff.is_supported(supported)
    assert not handoff.is_supported(temporary)
    dest = tmp_path / "inbox"
    dest.mkdir()
    (dest / "lecture.pdf").write_bytes(b"existing")
    result = handoff.unique_destination(dest, "lecture.pdf", "2026-09-16")
    assert result.name == "lecture (School Portal 2026-09-16).pdf"
