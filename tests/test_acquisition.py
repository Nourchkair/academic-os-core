from __future__ import annotations

from pathlib import Path

from academia_os.acquisition import import_file


def test_import_file_source_label_replaces_temporary_path_in_upload_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "University"
    destination = workspace / "Fall 2026" / "00_INBOX"
    destination.mkdir(parents=True)
    source = tmp_path / "temporary-source-name.pdf"
    source.write_bytes(b"browser bytes")

    value = import_file(
        source,
        destination,
        workspace_root=workspace,
        source_label="browser-upload:week-4.pdf",
    )

    assert value["source_type"] == "browser_upload"
    assert value["source_label"] == "browser-upload:week-4.pdf"
    assert value["original_file"] == "browser-upload:week-4.pdf"
    assert str(source) not in value.values()
    assert (destination / source.name).read_bytes() == b"browser bytes"
