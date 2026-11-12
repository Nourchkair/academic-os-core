from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.activity import ActivityLog
from academia_os.tasks import (
    TASK_BLOCK_END,
    TASK_BLOCK_START,
    TaskStateError,
    TaskStore,
)
from academia_os.workspace import build_workspace_snapshot
from tests.test_agent_interface import prepared_workspace


def _tasks_path(root: Path) -> Path:
    return root / "Fall 2026" / "SEMESTER_TASKS.md"


def test_create_preserves_unrelated_markdown_and_writes_one_block(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    path = _tasks_path(root)
    path.write_text(
        "# Semester Tasks\n\nMy own notes stay here.\n\n"
        f"{TASK_BLOCK_START}\n{{\"schema_version\": 1, \"tasks\": []}}\n{TASK_BLOCK_END}\n\n"
        "Trailing note.\n",
        encoding="utf-8",
    )
    store = TaskStore(root, "Fall 2026")
    task = store.create(
        title="Read Week 4",
        course_id="POL 2103",
        due_date="2026-09-24",
        due_time="09:30",
    )

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Semester Tasks\n\nMy own notes stay here.\n\n")
    assert text.endswith("\n\nTrailing note.\n")
    assert text.count(TASK_BLOCK_START) == 1
    assert task["course_id"] == "POL 2103 - Politics"
    assert task["provenance"] == "USER-CREATED"
    assert task["status"] == "open"
    assert store.list()[0]["id"] == task["id"]


def test_create_initializes_a_missing_file_and_records_activity(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    task = TaskStore(root, "Fall 2026").create(title="Plan the week")

    text = _tasks_path(root).read_text(encoding="utf-8")
    assert text.startswith("# Fall 2026")
    assert TASK_BLOCK_START in text
    events = ActivityLog(root / ".academia" / "activity.jsonl").list()
    assert events[0].event_type == "task.created"
    assert events[0].details["task_id"] == task["id"]


def test_complete_and_reopen_update_only_the_task(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    store = TaskStore(root, "Fall 2026")
    first = store.create(title="First")
    second = store.create(title="Second")

    completed = store.complete(first["id"])
    assert completed["status"] == "done"
    assert completed["completed_at"]
    assert store.list()[0]["id"] == second["id"]

    reopened = store.reopen(f"task:{first['id']}")
    assert reopened["status"] == "open"
    assert reopened["completed_at"] is None
    assert {task["id"] for task in store.list()} == {first["id"], second["id"]}
    event_types = [event.event_type for event in ActivityLog(root / ".academia" / "activity.jsonl").list()]
    assert event_types == ["task.updated", "task.completed", "task.created", "task.created"]


def test_update_rejects_invalid_values_without_rewriting(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    store = TaskStore(root, "Fall 2026")
    task = store.create(title="Keep me")
    before = _tasks_path(root).read_bytes()

    with pytest.raises(TaskStateError, match="real calendar date"):
        store.update(task["id"], due_date="2026-02-31")
    with pytest.raises(TaskStateError, match="needs a due date"):
        store.update(task["id"], due_time="09:00")
    with pytest.raises(TaskStateError, match="unknown or ambiguous course"):
        store.update(task["id"], course_id="Nope 101")

    assert _tasks_path(root).read_bytes() == before


def test_malformed_or_duplicate_blocks_fail_closed(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    path = _tasks_path(root)
    path.write_text(f"# Notes\n\n{TASK_BLOCK_START}\nnot json\n{TASK_BLOCK_END}\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(TaskStateError, match="not valid JSON"):
        TaskStore(root, "Fall 2026").create(title="Never written")
    assert path.read_bytes() == before

    path.write_text(
        f"{TASK_BLOCK_START}\n{{\"schema_version\": 1, \"tasks\": []}}\n{TASK_BLOCK_END}\n"
        f"{TASK_BLOCK_START}\n{{\"schema_version\": 1, \"tasks\": []}}\n{TASK_BLOCK_END}\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    with pytest.raises(TaskStateError, match="more than one task block"):
        TaskStore(root, "Fall 2026").create(title="Never written")
    assert path.read_bytes() == before


def test_invalid_task_fields_are_rejected(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    path = _tasks_path(root)
    payload = {
        "schema_version": 1,
        "tasks": [{
            "id": "one",
            "title": "Bad",
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00",
            "status": "done",
        }],
    }
    path.write_text(f"{TASK_BLOCK_START}\n{json.dumps(payload)}\n{TASK_BLOCK_END}\n", encoding="utf-8")
    with pytest.raises(TaskStateError, match="completed tasks need completed_at"):
        TaskStore(root, "Fall 2026").list()


def test_workspace_projection_separates_user_tasks_and_derived_tasks(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    store = TaskStore(root, "Fall 2026")
    user_task = store.create(title="User task", due_date="2026-09-20")
    cancelled = store.create(title="Cancelled task")
    store.update(cancelled["id"], status="cancelled")

    snapshot = build_workspace_snapshot(config, persist=False)
    by_id = {task["id"]: task for task in snapshot["tasks"]}
    assert by_id[f"task:{user_task['id']}"]["user_task"] is True
    assert by_id[f"task:{user_task['id']}"]["kind"] == "user_task"
    assert f"task:{cancelled['id']}" not in by_id
    assert any(task["source"].endswith("Course_Status.md") for task in snapshot["tasks"])
    assert snapshot["task_state_error"] is None


def test_workspace_projection_reports_a_malformed_task_block(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    _tasks_path(root).write_text(f"{TASK_BLOCK_START}\nbroken\n{TASK_BLOCK_END}\n", encoding="utf-8")
    snapshot = build_workspace_snapshot(config, persist=False)
    assert "not valid JSON" in snapshot["task_state_error"]
    assert all(not task.get("user_task") for task in snapshot["tasks"])


def test_coursework_history_never_completes_a_user_task(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    TaskStore(root, "Fall 2026").create(title="Read Week 4", course_id="POL 2103")
    # Exercise the overlay directly to keep this focused on the separation rule.
    from academia_os.assignment_history import apply_history_to_tasks
    user_task = {"id": "task:one", "title": "Read Week 4", "course": "POL 2103 - Politics", "user_task": True, "completed": False}
    derived = {"id": "derived:one", "title": "Read Week 4", "course": "POL 2103 - Politics", "completed": False}
    records = [{"title": "Read Week 4", "status": "completed", "task_title": "Read Week 4"}]
    result = apply_history_to_tasks([user_task, derived], records, course_name="POL 2103 - Politics")
    assert result[0]["completed"] is False
    assert result[1]["completed"] is True


def test_cli_task_create_complete_reopen_and_list(tmp_path: Path) -> None:
    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    created = run_cli(profile, "task", "create", "--title", "Read Week 4", "--course", "POL 2103", "--due-date", "2026-09-24", "--json")
    assert created.returncode == 0, created.stderr
    task = json.loads(created.stdout)
    assert task["course_id"] == "POL 2103 - Politics"

    listed = run_cli(profile, "task", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    payload = json.loads(listed.stdout)
    assert payload["task_state_error"] is None
    assert payload["tasks"][0]["task_id"] == task["id"]
    assert payload["tasks"][0]["id"] == f"task:{task['id']}"
    assert payload["tasks"][0]["completed"] is False
    assert payload["tasks"][0]["course"] == "POL 2103 - Politics"
    snapshot = build_workspace_snapshot(json.loads(profile.read_text(encoding="utf-8")), persist=False)
    workspace_task = next(item for item in snapshot["tasks"] if item.get("task_id") == task["id"])
    keys = ("id", "title", "completed", "course", "due_date", "due_time", "status")
    assert {key: workspace_task[key] for key in keys} == {key: payload["tasks"][0][key] for key in keys}

    completed = run_cli(profile, "task", "complete", task["id"], "--json")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "done"

    reopened = run_cli(profile, "task", "reopen", f"task:{task['id']}", "--json")
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout)["status"] == "open"

    updated = run_cli(profile, "task", "update", task["id"], "--clear-course", "--clear-due-date", "--status", "cancelled", "--json")
    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["course_id"] is None


def test_cli_task_list_reports_a_malformed_block_without_writing(tmp_path: Path) -> None:
    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    path = _tasks_path(root)
    path.write_text(f"{TASK_BLOCK_START}\nbroken\n{TASK_BLOCK_END}\n", encoding="utf-8")
    before = path.read_bytes()
    listed = run_cli(profile, "task", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    assert "not valid JSON" in json.loads(listed.stdout)["task_state_error"]

    failed = run_cli(profile, "task", "create", "--title", "Never written", "--json")
    assert failed.returncode == 2
    assert path.read_bytes() == before



def test_agent_context_keeps_semester_wide_tasks_out_of_course_scope(tmp_path: Path) -> None:
    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    store = TaskStore(root, "Fall 2026")
    store.create(title="Semester-wide task")
    store.create(title="Course task", course_id="POL 2103")

    workspace = run_cli(profile, "agent", "context", "--scope", "workspace", "--detail", "deep", "--json")
    assert workspace.returncode == 0, workspace.stderr
    workspace_titles = {task["title"] for task in json.loads(workspace.stdout)["current_state"]["open_tasks"]}
    assert {"Semester-wide task", "Course task"} <= workspace_titles

    course = run_cli(profile, "agent", "context", "--scope", "course", "--course", "POL 2103", "--detail", "deep", "--json")
    assert course.returncode == 0, course.stderr
    course_titles = {task["title"] for task in json.loads(course.stdout)["current_state"]["open_tasks"]}
    assert "Course task" in course_titles
    assert "Semester-wide task" not in course_titles


def test_create_appends_a_block_without_altering_existing_bytes(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    path = _tasks_path(root)
    path.write_text("# Notes\n\nKeep trailing spaces   \n\n", encoding="utf-8")
    before = path.read_bytes()

    TaskStore(root, "Fall 2026").create(title="Plan the week")

    after = path.read_bytes()
    assert after.startswith(before)
    assert after.decode("utf-8").count(TASK_BLOCK_START) == 1


def test_agent_context_reports_a_malformed_task_block(tmp_path: Path) -> None:
    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    _tasks_path(root).write_text(f"{TASK_BLOCK_START}\nbroken\n{TASK_BLOCK_END}\n", encoding="utf-8")
    context = run_cli(profile, "agent", "context", "--scope", "workspace", "--detail", "compact", "--json")
    assert context.returncode == 0, context.stderr
    assert "not valid JSON" in json.loads(context.stdout)["workspace"]["task_state_error"]


def test_atomic_replace_failure_leaves_the_task_file_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import academia_os.tasks as tasks_module

    _, root, _ = prepared_workspace(tmp_path)
    store = TaskStore(root, "Fall 2026")
    store.create(title="Keep me")
    path = _tasks_path(root)
    before = path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(tasks_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.create(title="Never written")
    assert path.read_bytes() == before
    assert [item for item in path.parent.glob(".SEMESTER_TASKS.md.*") if not item.name.endswith(".lock")] == []


def test_symlinked_task_file_fails_closed(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    target = tmp_path / "elsewhere.md"
    target.write_text("# Keep this target unchanged\n", encoding="utf-8")
    _tasks_path(root).symlink_to(target)

    with pytest.raises(TaskStateError, match="symbolic link"):
        TaskStore(root, "Fall 2026").create(title="Never written")
    assert target.read_text(encoding="utf-8") == "# Keep this target unchanged\n"


def test_duplicate_task_ids_fail_closed(tmp_path: Path) -> None:
    _, root, _ = prepared_workspace(tmp_path)
    task = {"id": "one", "title": "First", "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00"}
    path = _tasks_path(root)
    path.write_text(
        f"{TASK_BLOCK_START}\n{json.dumps({'schema_version': 1, 'tasks': [task, task]})}\n{TASK_BLOCK_END}\n",
        encoding="utf-8",
    )
    with pytest.raises(TaskStateError, match="duplicate task ids"):
        TaskStore(root, "Fall 2026").list()
