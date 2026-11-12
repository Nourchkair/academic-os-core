from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .course_identity import resolve_course_directory
from .state import JsonStateStore


HISTORY_FILENAME = "Assignment_History.json"
HISTORY_RELATIVE_PATH = Path("03_ASSIGNMENTS") / HISTORY_FILENAME
KINDS = frozenset({"assignment", "essay", "project", "exam", "presentation", "quiz", "other"})
STATUSES = frozenset({"planned", "in_progress", "submitted", "graded", "completed"})
TERMINAL_STATUSES = frozenset({"submitted", "graded", "completed"})
_FIELDS = frozenset({"kind", "title", "status", "due_date", "submitted_on", "grade", "task_title", "artifact_paths", "notes"})


def _text(value: Any, label: str, *, required: bool = False, limit: int = 200) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{label} is required")
    if "\x00" in cleaned or len(cleaned) > limit:
        raise ValueError(f"{label} is invalid or longer than {limit} characters")
    return cleaned or None


def _date(value: Any, label: str) -> str | None:
    cleaned = _text(value, label, limit=10)
    if cleaned is None:
        return None
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != cleaned:
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return cleaned


def _artifact_paths(course_root: Path, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("artifact_paths must be a list of at most 10 course-relative files")
    result: list[str] = []
    root = Path(course_root).resolve()
    for raw in value:
        cleaned = _text(raw, "artifact path", required=True, limit=500)
        candidate = Path(str(cleaned))
        if candidate.is_absolute() or not candidate.parts or any(part in {".", "..", ".academia"} for part in candidate.parts):
            raise ValueError("artifact paths must be relative to the course folder")
        current = root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("artifact paths cannot traverse symbolic links")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("artifact paths must point to existing files within the course folder") from exc
        if not resolved.is_file():
            raise ValueError("artifact paths must point to regular files")
        result.append(candidate.as_posix())
    return result


def validate_record_fields(course_root: Path, values: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("history record must be a JSON object")
    unknown = set(values) - _FIELDS
    if unknown:
        raise ValueError(f"unsupported history field(s): {', '.join(sorted(unknown))}")
    if not partial and not {"kind", "title", "status"}.issubset(values):
        raise ValueError("kind, title, and status are required")
    result: dict[str, Any] = {}
    if "kind" in values:
        kind = _text(values["kind"], "kind", required=True, limit=30)
        if kind not in KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        result["kind"] = kind
    if "title" in values:
        result["title"] = _text(values["title"], "title", required=True, limit=200)
    if "status" in values:
        status = _text(values["status"], "status", required=True, limit=30)
        if status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
        result["status"] = status
    if "due_date" in values:
        result["due_date"] = _date(values["due_date"], "due_date")
    if "submitted_on" in values:
        result["submitted_on"] = _date(values["submitted_on"], "submitted_on")
    if "grade" in values:
        result["grade"] = _text(values["grade"], "grade", limit=50)
    if "task_title" in values:
        result["task_title"] = _text(values["task_title"], "task_title", limit=200)
    if "artifact_paths" in values:
        result["artifact_paths"] = _artifact_paths(course_root, values["artifact_paths"])
    if "notes" in values:
        result["notes"] = _text(values["notes"], "notes", limit=2000)
    return result


def _history_path(course_root: Path) -> Path:
    assignments = Path(course_root) / "03_ASSIGNMENTS"
    if assignments.is_symlink():
        raise ValueError("the course assignment folder cannot be a symbolic link")
    return assignments / HISTORY_FILENAME


def list_assignment_history(workspace_root: Path, semester: str, course_id: str) -> list[dict[str, Any]]:
    course_root = resolve_course_directory(workspace_root, semester, course_id)
    path = _history_path(course_root)
    if path.is_symlink():
        raise ValueError("the assignment history file cannot be a symbolic link")
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read course assignment history: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("course_id") != course_root.name or value.get("semester") != semester or not isinstance(value.get("records"), list):
        raise ValueError(f"course assignment history has an unsupported or invalid structure: {path}")
    return [dict(record) for record in value["records"] if isinstance(record, dict)]


def _load_existing_for_write(path: Path, course_id: str, semester: str) -> dict[str, Any]:
    default = {"schema_version": 1, "semester": semester, "course_id": course_id, "records": []}
    if path.is_symlink():
        raise ValueError("the assignment history file cannot be a symbolic link")
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"refusing to replace invalid assignment history: {path}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("course_id") != course_id or value.get("semester") != semester or not isinstance(value.get("records"), list):
            raise ValueError(f"refusing to replace unsupported assignment history: {path}")
    return default


def add_assignment_history(workspace_root: Path, semester: str, course_id: str, values: dict[str, Any], *, actor: str = "user") -> dict[str, Any]:
    course_root = resolve_course_directory(workspace_root, semester, course_id)
    path = _history_path(course_root)
    default = _load_existing_for_write(path, course_root.name, semester)
    fields = validate_record_fields(course_root, values)
    now = datetime.now(timezone.utc).isoformat()
    actor = _text(actor, "actor", required=True, limit=80) or "user"
    status_event = {"status": fields["status"], "recorded_at": now, "actor": actor, "basis": "user-confirmed"}
    record = {
        "id": str(uuid4()),
        "semester": semester,
        "course_id": course_root.name,
        **fields,
        "artifact_paths": fields.get("artifact_paths", []),
        "notes": fields.get("notes"),
        "record_basis": "user-confirmed",
        "status_history": [status_event],
        "created_at": now,
        "updated_at": now,
        "actor": actor,
    }

    def append(raw: dict[str, Any]) -> dict[str, Any]:
        state = raw if isinstance(raw, dict) else default
        if state.get("schema_version") != 1 or state.get("course_id") != course_root.name or not isinstance(state.get("records"), list):
            raise ValueError("course assignment history changed to an unsupported structure")
        records = list(state["records"])
        records.append(record)
        return {**state, "semester": semester, "records": records}

    JsonStateStore(path).update_strict(default, append)
    return record


def update_assignment_history(workspace_root: Path, semester: str, course_id: str, record_id: str, values: dict[str, Any], *, actor: str = "user") -> dict[str, Any]:
    course_root = resolve_course_directory(workspace_root, semester, course_id)
    path = _history_path(course_root)
    default = _load_existing_for_write(path, course_root.name, semester)
    fields = validate_record_fields(course_root, values, partial=True)
    if not fields:
        raise ValueError("provide at least one history field to update")
    now = datetime.now(timezone.utc).isoformat()
    actor = _text(actor, "actor", required=True, limit=80) or "user"
    result: dict[str, Any] = {}

    def transform(raw: dict[str, Any]) -> dict[str, Any]:
        nonlocal result
        state = raw if isinstance(raw, dict) else default
        if state.get("schema_version") != 1 or state.get("course_id") != course_root.name or not isinstance(state.get("records"), list):
            raise ValueError("course assignment history changed to an unsupported structure")
        records = []
        found = False
        for raw_record in state["records"]:
            if not isinstance(raw_record, dict):
                raise ValueError("course assignment history contains an invalid record")
            record = dict(raw_record)
            if record.get("id") == record_id:
                found = True
                old_status = record.get("status")
                record.update(fields)
                record["updated_at"] = now
                record["actor"] = actor
                history = list(record.get("status_history", []))
                if "status" in fields and fields["status"] != old_status:
                    history.append({"status": fields["status"], "recorded_at": now, "actor": actor, "basis": "user-confirmed"})
                record["status_history"] = history
                result = record
            records.append(record)
        if not found:
            raise KeyError(f"assignment history record not found: {record_id}")
        return {**state, "semester": semester, "records": records}

    JsonStateStore(path).update_strict(default, transform)
    return result


def task_is_closed(record: dict[str, Any]) -> bool:
    return str(record.get("status", "")).casefold() in TERMINAL_STATUSES


def _match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def apply_history_to_tasks(tasks: list[dict[str, Any]], records: list[dict[str, Any]], *, course_name: str | None = None) -> list[dict[str, Any]]:
    """Overlay explicit user-confirmed terminal coursework status on derived tasks."""
    closed_titles = {_match_text(record.get("task_title") or record.get("title")) for record in records if task_is_closed(record)}
    closed_titles.discard("")
    result = []
    target_course = _match_text(course_name)
    for task_item in tasks:
        if task_item.get("user_task"):
            result.append(dict(task_item))
            continue
        item = dict(task_item)
        same_course = not target_course or _match_text(item.get("course")) == target_course
        if same_course and _match_text(item.get("title")) in closed_titles:
            matching = next(record for record in records if task_is_closed(record) and _match_text(record.get("task_title") or record.get("title")) == _match_text(item.get("title")))
            item["completed"] = True
            item["status"] = str(matching["status"]).replace("_", " ").title()
            if matching.get("grade") is not None:
                item["grade"] = matching["grade"]
        result.append(item)
    return result
