from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os import acquisition
from academia_os.acquisition import import_file
from academia_os.state import StateCorruptionError
from tests.test_agent_interface import prepared_workspace


def make_import_workspace(tmp_path: Path) -> tuple[Path, Path]:
    _, root, _ = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    return root, inbox


def test_import_records_content_hash_and_rejects_duplicate_content(tmp_path: Path) -> None:
    root, inbox = make_import_workspace(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")

    first = import_file(source, inbox, workspace_root=root)
    assert first["source_sha256"]
    assert first.get("duplicate") is not True
    assert Path(first["destination"]).read_text(encoding="utf-8") == "# Lecture\n"

    second = import_file(source, inbox, workspace_root=root)
    assert second["duplicate"] is True
    assert second["duplicate_of"] == "Fall 2026/POL 2103 - Politics/00_INBOX/lecture.md"
    assert second["destination"] == first["destination"]
    assert len(list(inbox.iterdir())) == 1

    records = json.loads((root / ".academia" / "acquisition.json").read_text(encoding="utf-8"))
    assert records["records"]["Fall 2026/POL 2103 - Politics/00_INBOX/lecture.md"]["source_sha256"] == first["source_sha256"]


def test_different_content_with_same_name_gets_a_new_name(tmp_path: Path) -> None:
    root, inbox = make_import_workspace(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("first", encoding="utf-8")
    first = import_file(source, inbox, workspace_root=root)
    source.write_text("second", encoding="utf-8")
    second = import_file(source, inbox, workspace_root=root)

    assert second.get("duplicate") is not True
    assert Path(second["destination"]).name == "lecture (import 1).md"
    assert Path(second["destination"]).read_text(encoding="utf-8") == "second"
    assert Path(first["destination"]).read_text(encoding="utf-8") == "first"


def test_corrupt_acquisition_state_blocks_copy_before_it_starts(tmp_path: Path) -> None:
    root, inbox = make_import_workspace(tmp_path)
    state = root / ".academia" / "acquisition.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not json", encoding="utf-8")
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")

    with pytest.raises(StateCorruptionError):
        import_file(source, inbox, workspace_root=root)
    assert list(inbox.iterdir()) == []
    assert state.read_text(encoding="utf-8") == "{not json"


def test_atomic_copy_failure_leaves_no_partial_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, inbox = make_import_workspace(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")

    def fail_link(*args, **kwargs):
        raise OSError("simulated link failure")

    monkeypatch.setattr(acquisition.os, "link", fail_link)
    with pytest.raises(OSError, match="simulated link failure"):
        import_file(source, inbox, workspace_root=root)
    assert list(inbox.iterdir()) == []
    assert source.read_text(encoding="utf-8") == "# Lecture\n"


def test_import_requires_workspace_root_and_valid_destination(tmp_path: Path) -> None:
    _, inbox = make_import_workspace(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")

    with pytest.raises(ValueError, match="workspace root"):
        import_file(source, inbox)
    with pytest.raises(ValueError, match="workspace inbox"):
        import_file(source, tmp_path, workspace_root=tmp_path)
