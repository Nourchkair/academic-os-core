from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.mcp_server import _resolve_scope
from tests.test_agent_interface import prepared_workspace
from tests.test_mcp_server import McpServer, call_error, call_json


def add_second_course(root: Path) -> Path:
    course = root / "Fall 2026" / "HIS 2101 - History"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "05_REFERENCE").mkdir()
    (course / "01_COURSE" / "Course_Status.md").write_text("# Status\n- [ ] Read Chapter 2\n", encoding="utf-8")
    (course / "05_REFERENCE" / "history.md").write_text("# History reading\n", encoding="utf-8")
    return course


def add_winter_course(root: Path) -> Path:
    course = root / "Winter 2027" / "BIO 1001 - Biology"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "05_REFERENCE").mkdir()
    (course / "01_COURSE" / "Course_Status.md").write_text("# Status\n- [ ] Read Chapter 1\n", encoding="utf-8")
    (course / "05_REFERENCE" / "biology.md").write_text("# Biology reading\n", encoding="utf-8")
    return course


def test_course_scope_filters_every_read_surface(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    add_second_course(root)
    server = McpServer(profile, read_only=True, course="POL 2103")
    try:
        courses = call_json(server, "academia_courses")
        assert [course["id"] for course in courses] == ["POL 2103 - Politics"]

        status = call_json(server, "academia_status")
        assert status["scope"] == {"semester": "Fall 2026", "course_id": "POL 2103 - Politics"}
        assert [course["id"] for course in status["workspace"]["courses"]] == ["POL 2103 - Politics"]

        library = call_json(server, "academia_library")
        assert library["items"]
        assert all(item["course_id"] == "POL 2103 - Politics" for item in library["items"])

        tasks = call_json(server, "academia_tasks")
        assert {task["course"] for task in tasks} == {"POL 2103 - Politics"}

        context = call_json(server, "academia_agent_context", {"scope": "workspace", "detail": "compact"})
        assert context["scope"]["course_id"] == "POL 2103 - Politics"

        targets = call_json(server, "academia_import_targets")
        assert [target["id"] for target in targets["targets"]] == ["Fall 2026/POL 2103 - Politics/00_INBOX"]

        other = "Fall 2026/HIS 2101 - History/05_REFERENCE/history.md"
        assert "outside the selected course" in call_error(server, "academia_read_library_item", {"id": other})
    finally:
        server.close()

    write_server = McpServer(profile, course="POL 2103")
    try:
        assert "outside the selected course" in call_error(
            write_server,
            "academia_import_file",
            {"source_path": str(root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"), "target_id": "Fall 2026/HIS 2101 - History/00_INBOX"},
        )
    finally:
        write_server.close()


def test_semester_scope_filters_cross_semester_reads(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    add_winter_course(root)
    server = McpServer(profile, read_only=True, semester="Winter 2027")
    try:
        courses = call_json(server, "academia_courses")
        assert [course["id"] for course in courses] == ["BIO 1001 - Biology"]

        status = call_json(server, "academia_status")
        assert status["scope"] == {"semester": "Winter 2027", "course_id": None}
        assert status["workspace"]["semester"] == "Winter 2027"
        assert [course["id"] for course in status["workspace"]["courses"]] == ["BIO 1001 - Biology"]

        library = call_json(server, "academia_library")
        assert [item["course_id"] for item in library["items"]] == ["BIO 1001 - Biology"]

        assert "selected semester" in call_error(
            server,
            "academia_read_library_item",
            {"id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"},
        )
    finally:
        server.close()


def test_unknown_scope_is_rejected_at_startup(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    with pytest.raises(ValueError, match="Unknown workspace semester"):
        _resolve_scope(profile, "Spring 2099", None)
    with pytest.raises(ValueError, match="Unknown or ambiguous course"):
        _resolve_scope(profile, "Fall 2026", "UNKNOWN")
