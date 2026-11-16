from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from academia_os.source_identity import (
    SourceIdentityError,
    fingerprint,
    identity,
    safe_workspace_path,
    short_version,
    source_id,
    validate_source_id,
)


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "05_REFERENCE").mkdir(parents=True)
    (course / "05_REFERENCE" / "reading.md").write_text("# Reading\n", encoding="utf-8")
    (root / "Fall 2026" / "semester.md").write_text("# Semester\n", encoding="utf-8")
    (root / ".academia").mkdir()
    (root / ".academia" / "index.json").write_text("{}", encoding="utf-8")
    (course / "linked.md").symlink_to(course / "05_REFERENCE" / "reading.md")
    return root


def test_safe_workspace_path_accepts_workspace_files_and_rejects_escapes(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    path = safe_workspace_path(root, "Fall 2026/POL 2103 - Politics/05_REFERENCE/reading.md")
    assert path.read_text(encoding="utf-8") == "# Reading\n"
    assert source_id(root, path) == "Fall 2026/POL 2103 - Politics/05_REFERENCE/reading.md"

    with pytest.raises(SourceIdentityError, match="hidden or parent"):
        safe_workspace_path(root, "../outside.md")
    with pytest.raises(SourceIdentityError, match="hidden or parent"):
        safe_workspace_path(root, ".academia/index.json")
    with pytest.raises(SourceIdentityError, match="symbolic links"):
        safe_workspace_path(root, "Fall 2026/POL 2103 - Politics/linked.md")
    assert safe_workspace_path(root, "Fall 2026").is_dir()


def test_missing_paths_can_be_checked_without_creating_them(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    missing = safe_workspace_path(root, "Fall 2026/new.md", allow_missing=True)
    assert not missing.exists()
    with pytest.raises(SourceIdentityError):
        safe_workspace_path(root, "Fall 2026/new.md")


def test_fingerprint_and_identity_are_content_based(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    path = root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "reading.md"
    expected = hashlib.sha256(path.read_bytes()).hexdigest()

    assert fingerprint(path) == expected
    value = identity(path, root=root)
    assert value["sha256"] == expected
    assert value["version"] == expected[:16]
    assert value["source_id"] == "Fall 2026/POL 2103 - Politics/05_REFERENCE/reading.md"
    assert value["size"] == path.stat().st_size

    path.write_text("# Changed\n", encoding="utf-8")
    changed = identity(path, root=root)
    assert changed["sha256"] != expected
    assert changed["version"] != value["version"]


def test_source_id_validation_requires_relative_regular_files(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    assert validate_source_id(root, "Fall 2026/POL 2103 - Politics/05_REFERENCE/reading.md").is_file()
    assert validate_source_id(root, "Fall 2026/semester.md").is_file()
    with pytest.raises(SourceIdentityError, match="selected semester"):
        validate_source_id(root, "Winter 2027/semester.md", semester="Fall 2026")
    with pytest.raises(SourceIdentityError, match="regular file"):
        validate_source_id(root, "Fall 2026")
    with pytest.raises(SourceIdentityError, match="POSIX"):
        validate_source_id(root, "Fall 2026\\semester.md")


def test_short_version_requires_a_digest() -> None:
    assert short_version("abcdef", length=4) == "abcd"
    with pytest.raises(SourceIdentityError):
        short_version("")
