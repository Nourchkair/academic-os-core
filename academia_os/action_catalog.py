"""Action tiers, previews, and executors for local workspace changes.

Every change the agent proposes goes through one catalog: a stable action type,
a validator, a human-readable preview, and an executor that verifies its own
work. Tiers decide how much approval a change needs:

``auto``
    Reversible and low stakes. Reserved for changes that are undone by an
    inverse action and never touch a file on disk.
``inline``
    One explicit student confirmation in the conversation. Tasks, imports,
    grade records, and trash restores.
``review``
    Full Review decision plus a separate execute. Moves, trashing, structural
    and settings changes.

Executors never delete: trashing moves a file into ``.academia/trash`` with a
restore record, and every executor re-reads the result before reporting success.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .actions import ActionProposal, ActionType
from .assignment_history import add_assignment_history, list_assignment_history, update_assignment_history
from .source_identity import SourceIdentityError, safe_workspace_path

TRASH_FOLDER = "trash"
TRASH_INDEX = "index.json"
MAX_HISTORY_RECORDS = 500


class ActionFrameworkError(ValueError):
    """An action could not be validated, previewed, or executed safely."""


class ActionTier(StrEnum):
    AUTO = "auto"
    INLINE = "inline"
    REVIEW = "review"


TIERS: dict[str, ActionTier] = {
    ActionType.TASK_CHANGE.value: ActionTier.INLINE,
    ActionType.COURSE_CREATE.value: ActionTier.INLINE,
    ActionType.SEMESTER_CREATE.value: ActionTier.INLINE,
    ActionType.FILE_COPY.value: ActionTier.INLINE,
    ActionType.GRADE_RECORD.value: ActionTier.INLINE,
    ActionType.FILE_RESTORE.value: ActionTier.INLINE,
    ActionType.FILE_MOVE.value: ActionTier.REVIEW,
    ActionType.FILE_TRASH.value: ActionTier.REVIEW,
    ActionType.CALENDAR_CHANGE.value: ActionTier.REVIEW,
    ActionType.CONFIGURATION_CHANGE.value: ActionTier.REVIEW,
    ActionType.DOMAIN_CHANGE.value: ActionTier.REVIEW,
}


@dataclass(frozen=True)
class ActionContext:
    workspace_root: Path
    state_root: Path
    semester: str
    profile_path: Path | None = None

    @property
    def root(self) -> Path:
        return self.workspace_root.resolve()

    @property
    def state(self) -> Path:
        return self.state_root.resolve()

    @property
    def trash_root(self) -> Path:
        return self.state / TRASH_FOLDER


def tier_for(action_type: str | ActionType) -> ActionTier:
    value = action_type.value if isinstance(action_type, ActionType) else str(action_type)
    return TIERS.get(value, ActionTier.REVIEW)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _details(proposal: ActionProposal) -> dict[str, Any]:
    value = proposal.details.get("proposal") if isinstance(proposal.details, dict) else None
    if isinstance(value, dict):
        return value
    return proposal.details if isinstance(proposal.details, dict) else {}


def _text(value: Any, label: str, *, limit: int = 400) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionFrameworkError(f"{label} is required")
    text = value.strip()
    if len(text) > limit:
        raise ActionFrameworkError(f"{label} is too long")
    return text


def _workspace_path(context: ActionContext, value: Any, label: str, *, allow_missing: bool = False) -> Path:
    text = _text(value, label, limit=2000)
    try:
        return safe_workspace_path(context.root, text, allow_missing=allow_missing)
    except SourceIdentityError as exc:
        raise ActionFrameworkError(str(exc)) from exc


def _trash_path(context: ActionContext, value: Any, label: str = "trashed path") -> Path:
    text = _text(value, label, limit=2000)
    candidate = (context.root / text).resolve()
    trash_root = context.trash_root.resolve()
    if candidate != trash_root and trash_root not in candidate.parents:
        raise ActionFrameworkError("trash paths must stay inside the trash store")
    return candidate


def _relative(context: ActionContext, path: Path) -> str:
    return path.resolve().relative_to(context.root).as_posix()


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


# --------------------------------------------------------------------------- trash


def _trash_index_path(context: ActionContext) -> Path:
    return context.trash_root / TRASH_INDEX


def _read_trash(context: ActionContext) -> list[dict[str, Any]]:
    path = _trash_index_path(context)
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ActionFrameworkError("the trash index could not be read") from exc
    entries = value.get("entries") if isinstance(value, dict) else None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def _write_trash(context: ActionContext, entries: list[dict[str, Any]]) -> None:
    context.trash_root.mkdir(parents=True, exist_ok=True)
    path = _trash_index_path(context)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {"schema_version": 1, "entries": entries[-MAX_HISTORY_RECORDS:]}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def list_trash(context: ActionContext) -> list[dict[str, Any]]:
    return [entry for entry in _read_trash(context) if not entry.get("restored_at")]


# --------------------------------------------------------------------------- preview


def _preview_move(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    source = _workspace_path(context, details.get("source"), "source path")
    destination = _workspace_path(context, details.get("destination"), "destination path", allow_missing=True)
    return {
        "title": "Move a workspace file",
        "summary": f"Move {_relative(context, source)} to {_relative(context, destination)}.",
        "changes": [
            {"label": "From", "from": _relative(context, source), "to": None},
            {"label": "To", "from": None, "to": _relative(context, destination)},
        ],
        "targets": [_relative(context, source), _relative(context, destination)],
    }


def _preview_trash(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    source = _workspace_path(context, details.get("path"), "file path")
    return {
        "title": "Move a file to trash",
        "summary": f"Remove {_relative(context, source)} from the workspace. It stays recoverable in .academia/trash.",
        "changes": [
            {"label": "File", "from": _relative(context, source), "to": ".academia/trash"},
        ],
        "targets": [_relative(context, source)],
    }


def _preview_restore(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    trash_id = _text(details.get("trash_id"), "trash entry", limit=80)
    entry = next((item for item in _read_trash(context) if item.get("id") == trash_id), None)
    if entry is None:
        raise ActionFrameworkError("that trash entry is not recorded")
    return {
        "title": "Restore a file from trash",
        "summary": f"Restore {entry.get('original')} to its original location.",
        "changes": [{"label": "Restore", "from": ".academia/trash", "to": str(entry.get("original"))}],
        "targets": [str(entry.get("original"))],
    }


def _preview_grade(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    values = details.get("values") if isinstance(details.get("values"), dict) else {}
    grade = values.get("grade")
    status = values.get("status")
    title = details.get("title") or details.get("record_id") or "coursework record"
    changes = []
    if status:
        changes.append({"label": "Status", "from": None, "to": str(status)})
    if grade:
        changes.append({"label": "Grade", "from": None, "to": str(grade)})
    return {
        "title": "Record a coursework grade",
        "summary": f"Update {title} in {details.get('course_id')}.",
        "changes": changes,
        "targets": [str(details.get("course_id") or "")],
    }


def _preview_task(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    title = details.get("title") or details.get("task_id") or "personal task"
    changes = []
    for label, key in (("Title", "title"), ("Due date", "due_date"), ("Due time", "due_time"), ("Course", "course_id")):
        if key in details and details.get(key) is not None:
            changes.append({"label": label, "from": None, "to": str(details.get(key))})
    return {
        "title": "Update a personal task",
        "summary": f"{details.get('action', 'update').title()} task: {title}.",
        "changes": changes,
        "targets": [str(details.get("task_id") or "")],
    }


def _preview_course(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    semester = str(details.get("semester") or context.semester)
    name = _text(details.get("name"), "course name", limit=200)
    return {
        "title": "Create a course workspace",
        "summary": f"Create {name} in {semester} from the course template.",
        "changes": [{"label": "New course", "from": None, "to": f"{semester}/{name}"}],
        "targets": [f"{semester}/{name}"],
    }


def _preview_semester(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    semester = _text(details.get("semester"), "semester", limit=80)
    return {
        "title": "Create a semester",
        "summary": f"Create the {semester} semester with its own inbox.",
        "changes": [{"label": "New semester", "from": None, "to": semester}],
        "targets": [semester],
    }


def _preview_settings(context: ActionContext, details: Mapping[str, Any]) -> dict[str, Any]:
    updates = details.get("updates") if isinstance(details.get("updates"), dict) else {}
    changes = [{"label": key, "from": details.get("before", {}).get(key) if isinstance(details.get("before"), dict) else None, "to": value} for key, value in updates.items()]
    return {
        "title": "Change Academia settings",
        "summary": f"Update {len(changes)} configuration value{'s' if len(changes) != 1 else ''}.",
        "changes": changes,
        "targets": ["profile.json"],
    }


_PREVIEWS = {
    ActionType.COURSE_CREATE.value: _preview_course,
    ActionType.SEMESTER_CREATE.value: _preview_semester,
    ActionType.CONFIGURATION_CHANGE.value: _preview_settings,
    ActionType.FILE_MOVE.value: _preview_move,
    ActionType.FILE_TRASH.value: _preview_trash,
    ActionType.FILE_RESTORE.value: _preview_restore,
    ActionType.GRADE_RECORD.value: _preview_grade,
    ActionType.TASK_CHANGE.value: _preview_task,
}


def preview(action_type: str | ActionType, details: Mapping[str, Any], context: ActionContext) -> dict[str, Any]:
    """Return the exact human-readable change set for one action."""

    value = action_type.value if isinstance(action_type, ActionType) else str(action_type)
    builder = _PREVIEWS.get(value)
    if builder is None:
        return {"title": value.replace("_", " ").title(), "summary": "This action is reviewed before it runs.", "changes": [], "targets": []}
    result = builder(context, details)
    return {"action_type": value, "tier": tier_for(value).value, **result}


# --------------------------------------------------------------------------- executors


def _execute_move(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    source = _workspace_path(context, details.get("source"), "source path", allow_missing=True)
    destination = _workspace_path(context, details.get("destination"), "destination path", allow_missing=True)
    if not source.is_file():
        raise ActionFrameworkError("the source file no longer exists")
    if destination.exists():
        raise ActionFrameworkError("the destination already exists")
    digest = _digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    if source.exists() or not destination.is_file():
        raise ActionFrameworkError("the move could not be verified")
    if _digest(destination) != digest:
        raise ActionFrameworkError("the moved file changed during the move")
    return {
        "verified": True,
        "source": _relative(context, source),
        "destination": _relative(context, destination),
        "sha256": digest,
        "actor": actor,
    }


def _execute_trash(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    source = _workspace_path(context, details.get("path"), "file path")
    if not source.is_file():
        raise ActionFrameworkError("only files that still exist can be trashed")
    entry_id = str(uuid.uuid4())
    digest = _digest(source)
    target_dir = context.trash_root / entry_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.move(str(source), str(target))
    if source.exists() or not target.is_file():
        raise ActionFrameworkError("the file could not be moved to trash")
    if _digest(target) != digest:
        raise ActionFrameworkError("the trashed file changed while it was moved")
    entries = _read_trash(context)
    entries.append({
        "id": entry_id,
        "original": _relative(context, source),
        "trashed": _relative(context, target),
        "sha256": digest,
        "created_at": _now(),
        "proposal_id": proposal.id,
        "actor": actor,
    })
    _write_trash(context, entries)
    if not _read_trash(context):
        raise ActionFrameworkError("the trash record could not be verified")
    return {
        "verified": True,
        "trash_id": entry_id,
        "original": _relative(context, source),
        "trashed": _relative(context, target),
        "sha256": digest,
        "restorable": True,
        "actor": actor,
    }


def _execute_restore(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    trash_id = _text(details.get("trash_id"), "trash entry", limit=80)
    entries = _read_trash(context)
    entry = next((item for item in entries if item.get("id") == trash_id), None)
    if entry is None:
        raise ActionFrameworkError("that trash entry is not recorded")
    if entry.get("restored_at"):
        raise ActionFrameworkError("that file was already restored")
    original = _workspace_path(context, entry.get("original"), "original path", allow_missing=True)
    trashed = _trash_path(context, entry.get("trashed"))
    if not trashed.is_file():
        raise ActionFrameworkError("the trashed file is no longer present")
    if original.exists():
        raise ActionFrameworkError("a file already exists at the original location")
    digest = _digest(trashed)
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trashed), str(original))
    if not original.is_file() or _digest(original) != digest:
        raise ActionFrameworkError("the restore could not be verified")
    entry["restored_at"] = _now()
    entry["restored_by"] = actor
    _write_trash(context, entries)
    return {
        "verified": True,
        "trash_id": trash_id,
        "restored": _relative(context, original),
        "sha256": digest,
        "actor": actor,
    }


def _execute_grade(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    course_id = _text(details.get("course_id"), "course", limit=300)
    semester = _text(details.get("semester"), "semester", limit=80) if details.get("semester") else context.semester
    values = details.get("values") if isinstance(details.get("values"), dict) else None
    if not values:
        raise ActionFrameworkError("grade records need at least one field")
    record_id = details.get("record_id")
    if record_id:
        record = update_assignment_history(context.root, semester, course_id, str(record_id), dict(values), actor=actor)
    else:
        record = add_assignment_history(context.root, semester, course_id, dict(values), actor=actor)
    stored = next((item for item in list_assignment_history(context.root, semester, course_id) if item.get("id") == record.get("id")), None)
    if stored is None:
        raise ActionFrameworkError("the coursework record could not be read back after saving")
    return {
        "verified": True,
        "record_id": stored.get("id"),
        "course_id": course_id,
        "semester": semester,
        "status": stored.get("status"),
        "grade": stored.get("grade"),
        "actor": actor,
    }


def _execute_course_create(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    name = _text(details.get("name"), "course name", limit=200)
    if "/" in name or "\\" in name or name in {".", ".."} or name.startswith("."):
        raise ActionFrameworkError("course names cannot contain path separators")
    semester = _text(details.get("semester"), "semester", limit=80) if details.get("semester") else context.semester
    semester_root = context.root / semester
    if not semester_root.is_dir():
        raise ActionFrameworkError(f"the semester {semester} does not exist yet")
    template = context.root / "COURSE_TEMPLATE"
    if not template.is_dir():
        raise ActionFrameworkError("this workspace has no COURSE_TEMPLATE to copy")
    target = semester_root / name
    if target.exists():
        raise ActionFrameworkError("a folder with that course name already exists")
    shutil.copytree(template, target)
    if not (target / "01_COURSE").is_dir():
        raise ActionFrameworkError("the course template is missing 01_COURSE")
    return {
        "verified": True,
        "course": name,
        "semester": semester,
        "path": target.relative_to(context.root).as_posix(),
        "actor": actor,
    }


def _execute_semester_create(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    details = _details(proposal)
    semester = _text(details.get("semester"), "semester", limit=80)
    from .course_identity import SEMESTER_PATTERN

    if SEMESTER_PATTERN.fullmatch(semester) is None:
        raise ActionFrameworkError("semester must use a term and four-digit year, for example Winter 2027")
    target = context.root / semester
    if target.exists():
        raise ActionFrameworkError("that semester already exists")
    template = context.root / "SEMESTER_TEMPLATE"
    if template.is_dir():
        shutil.copytree(template, target)
    else:
        (target / "00_INBOX").mkdir(parents=True)
    if not (target / "00_INBOX").is_dir():
        raise ActionFrameworkError("the semester folder was created without its inbox")
    return {
        "verified": True,
        "semester": semester,
        "path": target.relative_to(context.root).as_posix(),
        "actor": actor,
    }


def _execute_settings(proposal: ActionProposal, context: ActionContext, *, actor: str) -> dict[str, Any]:
    from .config import load_config, save_config
    from .settings import get_config_value, update_config

    details = _details(proposal)
    updates = details.get("updates") if isinstance(details.get("updates"), dict) else None
    if not updates:
        raise ActionFrameworkError("configuration changes need at least one setting")
    if context.profile_path is None:
        raise ActionFrameworkError("configuration changes need the local profile path")
    config = load_config(context.profile_path)
    candidate, changes = update_config(config, dict(updates), approve_structural=True)
    save_config(context.profile_path, candidate)
    stored = load_config(context.profile_path)
    for key, value in updates.items():
        if get_config_value(stored, str(key)) != value:
            raise ActionFrameworkError(f"the setting {key} could not be verified after saving")
    return {
        "verified": True,
        "changes": changes,
        "actor": actor,
    }


_EXECUTORS = {
    ActionType.COURSE_CREATE.value: _execute_course_create,
    ActionType.SEMESTER_CREATE.value: _execute_semester_create,
    ActionType.CONFIGURATION_CHANGE.value: _execute_settings,
    ActionType.FILE_MOVE.value: _execute_move,
    ActionType.FILE_TRASH.value: _execute_trash,
    ActionType.FILE_RESTORE.value: _execute_restore,
    ActionType.GRADE_RECORD.value: _execute_grade,
}


def execute_action(proposal: ActionProposal, context: ActionContext, *, actor: str = "user") -> dict[str, Any]:
    """Run one approved action and return its verification record."""

    if proposal.action_type == ActionType.TASK_CHANGE.value:
        from .assistant.tools.write import execute_task_change

        result = execute_task_change(proposal, workspace_root=context.root)
        return {"verified": True, "actor": actor, **(result if isinstance(result, dict) else {})}
    executor = _EXECUTORS.get(proposal.action_type)
    if executor is None:
        raise ActionFrameworkError(f"no executor is implemented for {proposal.action_type}")
    return executor(proposal, context, actor=actor)
