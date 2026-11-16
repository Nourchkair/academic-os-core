from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.import_preflight import PreflightError, preflight


def workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "University"
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir(parents=True)
    (root / "Fall 2026" / "00_INBOX").mkdir(parents=True)
    return root, inbox


def test_preflight_reports_size_support_and_duplicates(tmp_path: Path) -> None:
    root, inbox = workspace(tmp_path)
    source = tmp_path / "syllabus.pdf"
    source.write_bytes(b"course outline")
    (inbox / "syllabus.pdf").write_bytes(b"course outline")

    result = preflight([str(source)], str(inbox), root)
    record = result["files"][0]
    assert record["status"] == "ready"
    assert record["size"] == len(b"course outline")
    assert record["extractable"] is True
    assert record["ocr_may_be_needed"] is True
    assert record["duplicate"]["identical"] is True
    assert result["duplicates"] == 1


def test_preflight_flags_unsupported_and_missing(tmp_path: Path) -> None:
    root, inbox = workspace(tmp_path)
    binary = tmp_path / "archive.zip"
    binary.write_bytes(b"PK\x03\x04")
    result = preflight([str(binary), str(tmp_path / "cloud-placeholder.pdf")], str(inbox), root)
    assert result["files"][0]["extractable"] is False
    assert result["files"][1]["status"] == "missing"
    assert "iCloud" in result["files"][1]["reason"]


def test_preflight_rejects_destinations_outside_the_workspace(tmp_path: Path) -> None:
    root, _ = workspace(tmp_path)
    outside = tmp_path / "Elsewhere" / "00_INBOX"
    outside.mkdir(parents=True)
    with pytest.raises(PreflightError, match="inside the workspace"):
        preflight([str(tmp_path / "x.pdf")], str(outside), root)
    with pytest.raises(PreflightError, match="00_INBOX"):
        preflight([str(tmp_path / "x.pdf")], str(root / "Fall 2026"), root)
