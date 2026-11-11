from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os.actions import ActionStore, ActionType
from academia_os.processing import ProcessingStore, source_signature
from academia_os.review import ReviewQueue
from academia_os.state import JsonStateStore, StateCorruptionError
from academia_os.workflow_preferences import WorkflowPreferencesStore


def write_corrupt(path: Path, content: str = "{not json") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path.read_bytes()


def test_strict_reads_missing_state_as_a_copy_of_the_default(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path / "state.json")
    default = {"schema_version": 1, "items": []}
    value = store.read_strict(default)
    assert value == default
    value["items"].append("changed")
    assert default == {"schema_version": 1, "items": []}


def test_strict_read_rejects_invalid_json_and_wrong_top_level_type(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = write_corrupt(path)
    store = JsonStateStore(path)

    with pytest.raises(StateCorruptionError, match="not valid JSON") as error:
        store.read_strict([])
    assert error.value.path == path
    assert path.read_bytes() == original

    path.write_text(json.dumps({"unexpected": True}), encoding="utf-8")
    with pytest.raises(StateCorruptionError, match="unexpected top-level type"):
        store.read_strict([])


def test_quarantine_copies_without_deleting_the_damaged_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = write_corrupt(path)
    store = JsonStateStore(path)

    quarantine = store.quarantine()

    assert quarantine.is_file()
    assert quarantine.read_bytes() == original
    assert path.read_bytes() == original
    assert "corrupt-" in quarantine.name

    with pytest.raises(StateCorruptionError) as error:
        store.read_strict([], quarantine=True)
    assert error.value.quarantine_path is not None
    assert error.value.quarantine_path.is_file()


def test_strict_update_refuses_to_overwrite_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = write_corrupt(path)
    store = JsonStateStore(path)

    with pytest.raises(StateCorruptionError):
        store.update_strict([], lambda values: [*values, "new"])
    assert path.read_bytes() == original

    with pytest.raises(StateCorruptionError):
        store.update_strict([], lambda values: [*values, "new"], quarantine=True)
    assert path.read_bytes() == original


def test_strict_update_persists_valid_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = JsonStateStore(path)
    result = store.update_strict([], lambda values: [*values, {"id": "one"}])
    assert result == [{"id": "one"}]
    assert store.read_strict([]) == [{"id": "one"}]


def test_review_queue_fails_closed_on_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    original = write_corrupt(path)
    queue = ReviewQueue(path)

    with pytest.raises(StateCorruptionError):
        queue.list()
    with pytest.raises(StateCorruptionError):
        queue.add(kind="source_verification", title="Verify")
    assert path.read_bytes() == original


def test_action_store_fails_closed_on_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "actions.json"
    original = write_corrupt(path)
    actions = ActionStore(path)

    with pytest.raises(StateCorruptionError):
        actions.list()
    with pytest.raises(StateCorruptionError):
        actions.propose(action_type=ActionType.DOMAIN_CHANGE, title="Change")
    assert path.read_bytes() == original


def test_processing_store_fails_closed_on_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "processing.json"
    original = write_corrupt(path)
    store = ProcessingStore(path)
    source = tmp_path / "source.md"
    source.write_text("# Source\n", encoding="utf-8")

    with pytest.raises(StateCorruptionError):
        store.list()
    with pytest.raises(StateCorruptionError):
        store.detect(source, signature=source_signature(source))
    assert path.read_bytes() == original


def test_workflow_preferences_fail_closed_on_corrupt_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    path = root / ".academia" / "workflow_preferences.json"
    original = write_corrupt(path)
    store = WorkflowPreferencesStore(root)

    with pytest.raises(StateCorruptionError):
        store.list()
    with pytest.raises(StateCorruptionError):
        store.set("daily_academic_brief", preferences={"time": "08:30"})
    assert path.read_bytes() == original
