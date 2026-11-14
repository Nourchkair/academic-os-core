from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.agent_sessions import AgentSessionError, AgentSessionStore


def sample(session_id: str = "session-0001", **overrides: object) -> dict:
    value = {
        "id": session_id,
        "title": "Essay planning",
        "courseId": "course-1",
        "courseLabel": "POL 2108A · Modern Political Theory I",
        "messages": [
            {"role": "user", "content": "What is due soon?"},
            {"role": "assistant", "content": "An essay draft.", "attachments": [{"name": "a.pdf", "type": "application/pdf", "preview": "data:image/png;base64,AAAA"}]},
        ],
        "sourceIds": ["src-1"],
        "excludedCourseSourceIds": [],
        "updatedAt": "2026-11-13T10:00:00+00:00",
    }
    value.update(overrides)
    return value


def test_save_list_load_delete(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions")
    saved = store.save(sample())
    assert saved["schemaVersion"] == 1
    assert saved["messages"][1]["attachments"] == [{"name": "a.pdf", "type": "application/pdf"}]

    sessions = store.list()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "session-0001"
    assert sessions[0]["messageCount"] == 2
    assert sessions[0]["preview"] == "An essay draft."

    loaded = store.load("session-0001")
    assert loaded["title"] == "Essay planning"
    assert loaded["sourceIds"] == ["src-1"]

    store.delete("session-0001")
    assert store.list() == []
    store.delete("session-0001")  # deleting twice is safe


def test_rejects_unsafe_ids(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions")
    for bad in ("../escape", "a/b", "", "short", "x" * 80):
        with pytest.raises(AgentSessionError):
            store.save(sample(bad))
    with pytest.raises(AgentSessionError):
        store.load("..%2Fescape")


def test_requires_messages_and_sorts_newest_first(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions")
    with pytest.raises(AgentSessionError):
        store.save(sample(messages=[]))
    store.save(sample("session-0001", updatedAt="2026-11-10T10:00:00+00:00"))
    store.save(sample("session-0002", updatedAt="2026-11-12T10:00:00+00:00"))
    assert [item["id"] for item in store.list()] == ["session-0002", "session-0001"]


def test_ignores_corrupt_files(tmp_path: Path) -> None:
    directory = tmp_path / "agent_sessions"
    directory.mkdir()
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    store = AgentSessionStore(directory)
    assert store.list() == []
    store.save(sample())
    assert [item["id"] for item in store.list()] == ["session-0001"]


def test_state_is_plain_json_on_disk(tmp_path: Path) -> None:
    directory = tmp_path / "agent_sessions"
    store = AgentSessionStore(directory)
    store.save(sample())
    value = json.loads((directory / "session-0001.json").read_text(encoding="utf-8"))
    assert value["id"] == "session-0001"
    assert "preview" not in value["messages"][1]["attachments"][0]
