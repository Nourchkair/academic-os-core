from __future__ import annotations

from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest

from academia_os import cli
from academia_os.acquisition import validate_import_destination
from academia_os.semester import resolve_current_semester


def test_resolve_current_semester_handles_controlled_future_dates_and_timezones() -> None:
    assert resolve_current_semester(datetime(2027, 1, 15, 12), "America/Toronto") == "Winter 2027"
    assert resolve_current_semester(datetime(2027, 8, 1, 12), "America/Toronto") == "Summer 2027"
    assert resolve_current_semester(datetime(2027, 9, 15, 12), "America/Toronto") == "Fall 2027"


def test_workspace_create_uses_shared_resolver_when_semester_is_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "resolve_current_semester", lambda *, timezone_name: "Winter 2027")
    args = Namespace(
        path=tmp_path / "Fresh",
        name="Student",
        institution="Example University",
        program="History",
        semester="",
        timezone="America/Toronto",
        profile=tmp_path / ".academic-os" / "profile.json",
        apply=False,
    )

    result = cli._create_workspace(args)

    assert result["candidate"]["academic"]["semester"] == "Winter 2027"


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "University"
    semester = root / "Fall 2027"
    course = semester / "POL 3124 - Politics"
    (semester / "00_INBOX").mkdir(parents=True)
    (course / "01_COURSE").mkdir(parents=True)
    (course / "00_INBOX").mkdir()
    return root


def test_structural_import_validation_accepts_semester_and_course_inboxes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    assert validate_import_destination(root, root / "Fall 2027" / "00_INBOX") == (root / "Fall 2027" / "00_INBOX").resolve()
    assert validate_import_destination(root, root / "Fall 2027" / "POL 3124 - Politics" / "00_INBOX") == (root / "Fall 2027" / "POL 3124 - Politics" / "00_INBOX").resolve()


def test_import_file_requires_workspace_context_for_structural_validation(tmp_path: Path) -> None:
    from academia_os.acquisition import import_file

    root = _workspace(tmp_path)
    source = tmp_path / "reading.pdf"
    source.write_bytes(b"reading")

    with pytest.raises(ValueError, match="workspace root"):
        import_file(source, root / "Fall 2027" / "00_INBOX")


def test_structural_import_validation_rejects_fake_semesters_courses_and_nested_inboxes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    invalid = [
        root / "LooseDump" / "00_INBOX",
        root / "Fall 2027" / "RandomStuff" / "00_INBOX",
        root / "Fall 2027" / "POL 3124 - Politics" / "03_ASSIGNMENTS" / "00_INBOX",
        root / "Winter 2028" / "00_INBOX",
    ]

    for destination in invalid:
        with pytest.raises(ValueError, match="recognized|semester|course|direct"):
            validate_import_destination(root, destination)
