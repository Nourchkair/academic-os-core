"""Durable local storage for Academia agent conversations.

Sessions live under ``<academic root>/.academia/agent_sessions/`` as one JSON
file per conversation. This is student data, not a rebuildable cache: it keeps
the local record of what the assistant said and which proposals it prepared,
and it survives clearing browser storage.

Attachments keep their name and media type only. File bytes, extracted text,
and image previews are never written here.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
MAX_SESSIONS = 500
MAX_MESSAGES = 400
MAX_MESSAGE_CHARS = 200_000
MAX_TITLE_CHARS = 200
MAX_PROPOSALS = 20
MAX_ATTACHMENTS = 20
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MESSAGE_ROLES = {"user", "assistant"}


class AgentSessionError(ValueError):
    """A saved agent session could not be read or written safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:limit]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)][:500]


def _attachments(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in value[:MAX_ATTACHMENTS]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        media_type = item.get("type")
        if isinstance(name, str) and isinstance(media_type, str):
            cleaned.append({"name": name[:300], "type": media_type[:120]})
    return cleaned


def _proposals(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in value[:MAX_PROPOSALS]:
        if not isinstance(item, dict):
            continue
        entry = {
            "kind": _text(item.get("kind"), limit=60),
            "title": _text(item.get("title"), limit=300),
            "summary": _text(item.get("summary"), limit=2000),
            "effects": _string_list(item.get("effects"))[:20],
            "review_id": _text(item.get("review_id"), limit=120),
        }
        for key in ("proposal_id", "status", "action_status", "status_label"):
            if isinstance(item.get(key), str):
                entry[key] = item[key][:200]
        cleaned.append(entry)
    return cleaned


def _trace(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    steps: list[dict[str, Any]] = []
    for item in value[:40]:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        step = {"tool": tool[:120], "ok": bool(item.get("ok", True))}
        milliseconds = item.get("ms")
        if isinstance(milliseconds, int) and 0 <= milliseconds <= 3_600_000:
            step["ms"] = milliseconds
        steps.append(step)
    return steps


def _messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AgentSessionError("session messages must be a list")
    cleaned: list[dict[str, Any]] = []
    for item in value[-MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in MESSAGE_ROLES or not isinstance(content, str):
            continue
        message: dict[str, Any] = {"role": role, "content": content[:MAX_MESSAGE_CHARS]}
        at = item.get("at")
        if isinstance(at, str) and at:
            message["at"] = at[:40]
        attachments = _attachments(item.get("attachments"))
        if attachments:
            message["attachments"] = attachments
        proposals = _proposals(item.get("proposals"))
        if proposals:
            message["proposals"] = proposals
        mentions = item.get("mentions")
        if isinstance(mentions, list):
            kept = [entry for entry in mentions if isinstance(entry, str)][:8]
            if kept:
                message["mentions"] = [entry[:40] for entry in kept]
        trace = _trace(item.get("trace"))
        if trace:
            message["trace"] = trace
        cleaned.append(message)
    return cleaned


def normalize_session(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one conversation and return the exact shape stored on disk."""

    session_id = value.get("id")
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
        raise AgentSessionError("session id is not valid")
    messages = _messages(value.get("messages"))
    if not messages:
        raise AgentSessionError("a session must contain at least one message")
    updated_at = value.get("updatedAt")
    if not isinstance(updated_at, str) or not updated_at:
        updated_at = _now()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": session_id,
        "title": _text(value.get("title"), limit=MAX_TITLE_CHARS) or "Untitled chat",
        "courseId": _text(value.get("courseId"), limit=300),
        "courseLabel": _text(value.get("courseLabel"), limit=300) or "All Academia",
        "messages": messages,
        "sourceIds": _string_list(value.get("sourceIds")),
        "excludedCourseSourceIds": _string_list(value.get("excludedCourseSourceIds")),
        "createdAt": _text(value.get("createdAt"), limit=60) or updated_at,
        "updatedAt": updated_at,
    }


def summarize(session: Mapping[str, Any]) -> dict[str, Any]:
    last = session["messages"][-1] if session["messages"] else {}
    preview = str(last.get("content") or "")[:280]
    return {
        "id": session["id"],
        "title": session["title"],
        "courseId": session["courseId"],
        "courseLabel": session["courseLabel"],
        "messageCount": len(session["messages"]),
        "preview": preview,
        "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"],
    }


class AgentSessionStore:
    """One JSON file per conversation, written atomically."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).expanduser()

    def _ensure_directory(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
            raise AgentSessionError("session id is not valid")
        root = self.directory.resolve()
        path = (self.directory / f"{session_id}.json").resolve()
        if path.parent != root:
            raise AgentSessionError("session id is not valid")
        return path

    def _read_file(self, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        try:
            return normalize_session(value)
        except AgentSessionError:
            return None

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.is_dir():
            return []
        sessions: list[dict[str, Any]] = []
        for path in self._iter_files():
            session = self._read_file(path)
            if session is not None:
                sessions.append(session)
        sessions.sort(key=lambda item: str(item["updatedAt"]), reverse=True)
        return [summarize(session) for session in sessions]

    def _iter_files(self) -> Iterable[Path]:
        try:
            return sorted(self.directory.glob("*.json"))
        except OSError:
            return []

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.is_file():
            raise FileNotFoundError(session_id)
        session = self._read_file(path)
        if session is None:
            raise AgentSessionError("this conversation could not be read")
        return session

    def save(self, value: Mapping[str, Any]) -> dict[str, Any]:
        session = normalize_session(value)
        directory = self._ensure_directory()
        path = self._path(str(session["id"]))
        temporary = directory / f".{session['id']}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        self._prune(exclude=str(session["id"]))
        return session

    def _prune(self, *, exclude: str) -> None:
        sessions = self.list()
        if len(sessions) <= MAX_SESSIONS:
            return
        for summary in sessions[MAX_SESSIONS:]:
            if summary["id"] == exclude:
                continue
            try:
                self._path(str(summary["id"])).unlink(missing_ok=True)
            except (OSError, AgentSessionError):
                continue

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise AgentSessionError(f"the conversation could not be deleted: {exc}") from exc

    def new_id(self) -> str:
        return str(uuid.uuid4())
