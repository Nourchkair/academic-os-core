from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.assignment_history import add_assignment_history, apply_history_to_tasks, list_assignment_history, update_assignment_history
from academia_os.library import list_material


def _course(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "University"
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "03_ASSIGNMENTS" / "A01" / "Submission").mkdir(parents=True)
    (course / "03_ASSIGNMENTS" / "A01" / "Submission" / "final.docx").write_bytes(b"final document")
    return root, course


def test_history_is_course_scoped_user_confirmed_and_status_updates_are_retained(tmp_path: Path) -> None:
    root, course = _course(tmp_path)
    record = add_assignment_history(root, "Fall 2026", course.name, {
        "kind": "essay",
        "title": "First Essay — Question 3",
        "task_title": "First Essay",
        "status": "submitted",
        "due_date": "2026-10-08",
        "submitted_on": "2026-10-08",
        "artifact_paths": ["03_ASSIGNMENTS/A01/Submission/final.docx"],
    })

    assert record["record_basis"] == "user-confirmed"
    assert list_assignment_history(root, "Fall 2026", course.name) == [record]
    assert all(item["name"] != "Assignment_History.json" for item in list_material(root, "Fall 2026"))
    assert apply_history_to_tasks([{"title": "First Essay", "course": course.name, "completed": False}], [record], course_name=course.name)[0] == {
        "title": "First Essay", "course": course.name, "completed": True, "status": "Submitted",
    }
    other_course_tasks = [{"title": "First Essay", "course": "HIS 101 - History", "completed": False}]
    assert apply_history_to_tasks(other_course_tasks, [record], course_name=course.name)[0]["completed"] is False

    updated = update_assignment_history(root, "Fall 2026", course.name, record["id"], {"status": "graded", "grade": "A"})
    assert updated["grade"] == "A"
    assert [item["status"] for item in updated["status_history"]] == ["submitted", "graded"]


def test_history_rejects_artifacts_outside_course_and_invalid_dates(tmp_path: Path) -> None:
    root, course = _course(tmp_path)
    base = {"kind": "assignment", "title": "Test", "status": "submitted"}
    with pytest.raises(ValueError, match="relative to the course"):
        add_assignment_history(root, "Fall 2026", course.name, {**base, "artifact_paths": ["../../outside.docx"]})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        add_assignment_history(root, "Fall 2026", course.name, {**base, "due_date": "08/10/2026"})
    assert not (course / "03_ASSIGNMENTS" / "Assignment_History.json").exists()


def test_history_cli_add_and_list_are_machine_readable(tmp_path: Path) -> None:
    from tests.test_cli import run_cli

    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "First Essay",
        "--status", "submitted", "--due-date", "2026-10-08", "--submitted-on", "2026-10-08",
        "--task-title", "First Essay", "--json",
    )
    assert added.returncode == 0, added.stderr
    value = json.loads(added.stdout)
    assert value["title"] == "First Essay"

    listed = run_cli(tmp_path, "history", "list", "--course", "POL 2103 - Politics", "--json")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)[0]["status"] == "submitted"


def test_submitted_history_closes_its_matching_dashboard_task(tmp_path: Path) -> None:
    from tests.test_agent_neutral_core import minimal_config
    from academia_os.config import save_config
    from academia_os.domain import Assignment, DomainProjection, Evidence
    from tests.test_cli import run_cli

    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    DomainProjection(root / ".academia" / "domain.json").upsert(Assignment(
        id="essay-1", course_id=course.name, title="First Essay", deadline="2026-10-08", weight="25%",
        instructions_source=None, rubric_source=None, submission_method=None, status=None,
        evidence=Evidence(source="Syllabus", source_path=str(course / "01_COURSE" / "syllabus.pdf"), confidence="current-confirmed", authority="course syllabus"),
    ))
    add_assignment_history(root, "Fall 2026", course.name, {
        "kind": "essay", "title": "First Essay — Question 3", "task_title": "First Essay", "status": "submitted",
    })

    result = run_cli(tmp_path, "tasks", "--json")

    assert result.returncode == 0, result.stderr
    task = next(item for item in json.loads(result.stdout) if item["title"] == "First Essay")
    assert task["completed"] is True
    assert task["status"] == "Submitted"

    context_result = run_cli(tmp_path, "agent", "context", "--scope", "course", "--course", course.name, "--json")
    assert context_result.returncode == 0, context_result.stderr
    context = json.loads(context_result.stdout)
    assert context["current_state"]["assignment_history"][0]["status"] == "submitted"
    assert all(task["title"] != "First Essay" for task in context["current_state"]["open_tasks"])
