"""Canonical user-owned task queue stored inside SEMESTER_TASKS.md.

The academic workspace remains the source of truth.  User tasks live in one
explicitly delimited JSON block inside the semester's Markdown task file; all
unrelated Markdown is preserved byte-for-byte.  Derived course tasks and domain
deadlines are separate evidence and are never written here.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .activity import ActivityLog
from .config import SEMESTER_PATTERN
from .course_identity import course_records, resolve_course_identifier
from .state import JsonStateStore

TASK_SCHEMA_VERSION = 1
TASK_BLOCK_START = "<!-- academia:tasks:start -->"
TASK_BLOCK_END = "<!-- academia:tasks:end -->"
TASK_STATUSES = frozenset({"open", "done", "cancelled"})
TASK_PROVENANCE = frozenset({"USER-CREATED", "AI-GENERATED"})
_TASK_BLOCK = re.compile(re.escape(TASK_BLOCK_START) + r"\s*(.*?)\s*" + re.escape(TASK_BLOCK_END), re.DOTALL)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{2}:\d{2}$")


class TaskStateError(ValueError):
    """The task block is unreadable or invalid; it is never silently replaced."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, field: str, *, maximum: int = 300, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise TaskStateError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _validate_date(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise TaskStateError("due_date must use YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise TaskStateError("due_date must be a real calendar date") from exc
    return value


def _validate_time(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise TaskStateError("due_time must use HH:MM")
    hour, minute = (int(part) for part in value.split(":", 1))
    if hour > 23 or minute > 59:
        raise TaskStateError("due_time must be a valid 24-hour time")
    return value


def _validate_task(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskStateError("task entries must be objects")
    task_id = _text(value.get("id"), "task id", maximum=80)
    title = _text(value.get("title"), "title")
    course_id = value.get("course_id")
    if course_id is not None and not isinstance(course_id, str):
        raise TaskStateError("course_id must be a string or null")
    due_date = _validate_date(value.get("due_date"))
    due_time = _validate_time(value.get("due_time"))
    if due_time and not due_date:
        raise TaskStateError("a task with a due time needs a due date")
    status = value.get("status", "open")
    if status not in TASK_STATUSES:
        raise TaskStateError("task status must be open, done, or cancelled")
    provenance = value.get("provenance", "USER-CREATED")
    if provenance not in TASK_PROVENANCE:
        raise TaskStateError("task provenance is invalid")
    source = _text(value.get("source", "user"), "source", maximum=120)
    created_at = _text(value.get("created_at"), "created_at", maximum=80)
    updated_at = _text(value.get("updated_at"), "updated_at", maximum=80)
    completed_at = value.get("completed_at")
    if completed_at is not None:
        completed_at = _text(completed_at, "completed_at", maximum=80)
    if status == "done" and not completed_at:
        raise TaskStateError("completed tasks need completed_at")
    if status != "done":
        completed_at = None
    return {
        "id": task_id,
        "title": title,
        "course_id": course_id,
        "due_date": due_date,
        "due_time": due_time,
        "status": status,
        "provenance": provenance,
        "source": source,
        "created_at": created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
    }


def _empty_state() -> dict[str, Any]:
    return {"schema_version": TASK_SCHEMA_VERSION, "tasks": []}


def project_task(task: dict[str, Any], semester: str) -> dict[str, Any]:
    """Return one task in the shared workspace/UI projection shape."""
    return {
        "id": f"task:{task['id']}",
        "task_id": task["id"],
        "title": task["title"],
        "completed": task["status"] == "done",
        "course": task.get("course_id"),
        "source": f"{semester}/SEMESTER_TASKS.md",
        "source_location": f"task:{task['id']}",
        "confidence": "user-confirmed" if task["provenance"] == "USER-CREATED" else "unverified",
        "kind": "user_task",
        "user_task": True,
        "provenance": task["provenance"],
        "due_date": task.get("due_date"),
        "due_time": task.get("due_time"),
        "status": task["status"],
    }


class TaskStore:
    def __init__(self, workspace_root: Path, semester: str) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if SEMESTER_PATTERN.fullmatch(semester) is None:
            raise ValueError("semester must use a term and four-digit year")
        self.root = root
        self.semester = semester
        self.path = root / semester / "SEMESTER_TASKS.md"
        self._lock = JsonStateStore(self.path)

    def _activity(self) -> ActivityLog:
        return ActivityLog(self.root / ".academia" / "activity.jsonl")

    def _read_text(self) -> str:
        if self.path.is_symlink():
            raise TaskStateError("SEMESTER_TASKS.md must not be a symbolic link")
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TaskStateError("SEMESTER_TASKS.md could not be read") from exc

    def read(self) -> dict[str, Any]:
        text = self._read_text()
        matches = list(_TASK_BLOCK.finditer(text))
        if not matches:
            return _empty_state()
        if len(matches) > 1:
            raise TaskStateError("SEMESTER_TASKS.md contains more than one task block")
        try:
            value = json.loads(matches[0].group(1))
        except json.JSONDecodeError as exc:
            raise TaskStateError("the SEMESTER_TASKS.md task block is not valid JSON") from exc
        if not isinstance(value, dict) or value.get("schema_version") != TASK_SCHEMA_VERSION or not isinstance(value.get("tasks"), list):
            raise TaskStateError("unsupported SEMESTER_TASKS.md task block")
        tasks = [_validate_task(task) for task in value["tasks"]]
        if len({task["id"] for task in tasks}) != len(tasks):
            raise TaskStateError("SEMESTER_TASKS.md contains duplicate task ids")
        return {"schema_version": TASK_SCHEMA_VERSION, "tasks": tasks}

    def list(self) -> list[dict[str, Any]]:
        return sorted(
            self.read()["tasks"],
            key=lambda task: (task["status"] != "open", task.get("due_date") or "9999-99-99", task.get("due_time") or "", task["title"].casefold()),
        )

    def get(self, task_id: str) -> dict[str, Any]:
        raw_id = task_id[5:] if task_id.startswith("task:") else task_id
        for task in self.read()["tasks"]:
            if task["id"] == raw_id:
                return task
        raise KeyError(f"task not found: {task_id}")

    def _validate_course(self, course_id: str | None) -> str | None:
        if not course_id:
            return None
        try:
            return str(resolve_course_identifier(course_records(self.root / self.semester), course_id)["id"])
        except (KeyError, ValueError) as exc:
            raise TaskStateError(f"unknown or ambiguous course: {course_id}") from exc

    def _render(self, tasks: list[dict[str, Any]]) -> str:
        payload = json.dumps({"schema_version": TASK_SCHEMA_VERSION, "tasks": tasks}, indent=2, ensure_ascii=False, sort_keys=True)
        return f"{TASK_BLOCK_START}\n{payload}\n{TASK_BLOCK_END}"

    def _write(self, tasks: list[dict[str, Any]]) -> None:
        text = self._read_text()
        block = self._render(tasks)
        matches = list(_TASK_BLOCK.finditer(text))
        if len(matches) > 1:
            raise TaskStateError("SEMESTER_TASKS.md contains more than one task block")
        if matches:
            updated = text[:matches[0].start()] + block + text[matches[0].end():]
        elif text:
            separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
            updated = text + separator + block + "\n"
        else:
            updated = f"# {self.semester} — Semester Tasks\n\n{block}\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _mutate(
        self,
        transform: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], dict[str, Any]]],
    ) -> dict[str, Any]:
        """Read, transform, and atomically replace the task block under one lock."""
        with self._lock.locked():
            state = self.read()
            tasks, result = transform(state["tasks"])
            self._write(tasks)
            return result

    def new_task(
        self,
        *,
        title: str,
        course_id: str | None = None,
        due_date: str | None = None,
        due_time: str | None = None,
        provenance: str = "USER-CREATED",
        source: str = "user",
    ) -> dict[str, Any]:
        """Build and validate one future task without writing it."""
        now = _now()
        return _validate_task({
            "id": str(uuid4()),
            "title": title,
            "course_id": self._validate_course(course_id),
            "due_date": due_date,
            "due_time": due_time,
            "status": "open",
            "provenance": provenance,
            "source": source,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        })

    def _apply_fields(
        self,
        task: dict[str, Any],
        *,
        title: str | None = None,
        course_id: str | None | object = ...,
        due_date: str | None | object = ...,
        due_time: str | None | object = ...,
        status: str | None = None,
    ) -> dict[str, Any]:
        updated = dict(task)
        if title is not None:
            updated["title"] = title
        if course_id is not ...:
            updated["course_id"] = self._validate_course(course_id if isinstance(course_id, str) else None)
        if due_date is not ...:
            updated["due_date"] = due_date
        if due_time is not ...:
            updated["due_time"] = due_time
        if status is not None:
            if status not in TASK_STATUSES:
                raise TaskStateError("task status must be open, done, or cancelled")
            updated["status"] = status
            updated["completed_at"] = _now() if status == "done" else None
        updated["updated_at"] = _now()
        return _validate_task(updated)

    def preview_update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        course_id: str | None | object = ...,
        due_date: str | None | object = ...,
        due_time: str | None | object = ...,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Validate a future update without changing SEMESTER_TASKS.md."""
        return self._apply_fields(self.get(task_id), title=title, course_id=course_id, due_date=due_date, due_time=due_time, status=status)

    def create(
        self,
        *,
        title: str,
        course_id: str | None = None,
        due_date: str | None = None,
        due_time: str | None = None,
        provenance: str = "USER-CREATED",
        source: str = "user",
        actor: str = "user",
    ) -> dict[str, Any]:
        task = self.new_task(
            title=title,
            course_id=course_id,
            due_date=due_date,
            due_time=due_time,
            provenance=provenance,
            source=source,
        )
        self._mutate(lambda tasks: ([*tasks, task], task))
        self._activity().append(
            event_type="task.created",
            title=f"Task created: {task['title']}",
            course=task.get("course_id"),
            source=f"{self.semester}/SEMESTER_TASKS.md",
            confidence="user-confirmed" if task["provenance"] == "USER-CREATED" else "unverified",
            actor=actor,
            details={"task_id": task["id"], "status": task["status"], "due_date": task.get("due_date"), "due_time": task.get("due_time")},
        )
        return task

    def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        course_id: str | None | object = ...,
        due_date: str | None | object = ...,
        due_time: str | None | object = ...,
        status: str | None = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        raw_id = task_id[5:] if task_id.startswith("task:") else task_id
        updated_task: dict[str, Any] | None = None

        def transform(existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            nonlocal updated_task
            tasks: list[dict[str, Any]] = []
            for task in existing:
                if task["id"] != raw_id:
                    tasks.append(task)
                    continue
                updated_task = self._apply_fields(
                    task,
                    title=title,
                    course_id=course_id,
                    due_date=due_date,
                    due_time=due_time,
                    status=status,
                )
                tasks.append(updated_task)
            if updated_task is None:
                raise KeyError(f"task not found: {task_id}")
            return tasks, updated_task

        updated_task = self._mutate(transform)
        event = "task.completed" if updated_task["status"] == "done" else "task.updated"
        self._activity().append(
            event_type=event,
            title=f"Task {'completed' if event == 'task.completed' else 'updated'}: {updated_task['title']}",
            course=updated_task.get("course_id"),
            source=f"{self.semester}/SEMESTER_TASKS.md",
            confidence="user-confirmed" if updated_task["provenance"] == "USER-CREATED" else "unverified",
            actor=actor,
            details={"task_id": updated_task["id"], "status": updated_task["status"], "due_date": updated_task.get("due_date"), "due_time": updated_task.get("due_time")},
        )
        return updated_task

    def complete(self, task_id: str, *, actor: str = "user") -> dict[str, Any]:
        return self.update(task_id, status="done", actor=actor)

    def reopen(self, task_id: str, *, actor: str = "user") -> dict[str, Any]:
        return self.update(task_id, status="open", actor=actor)
