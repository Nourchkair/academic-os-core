from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from academia_os.file_preview import FilePreviewError, preview_file


def _inbox(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "University"
    inbox = root / "Fall 2026" / "HIS 101 - History" / "00_INBOX"
    inbox.mkdir(parents=True)
    return root, inbox


def test_markdown_preview_reads_only_active_semester_library_material(tmp_path: Path) -> None:
    root, inbox = _inbox(tmp_path)
    source = inbox / "week-4.md"
    source.write_text("# Week 4\n\nRead the primary source.", encoding="utf-8")

    result = preview_file(source, workspace_root=root, semester="Fall 2026")

    assert result["kind"] == "text"
    assert result["name"] == "week-4.md"
    assert result["content"] == "# Week 4\n\nRead the primary source."
    assert result["truncated"] is False


def test_pdf_preview_extracts_readable_content_without_mutating_source(tmp_path: Path) -> None:
    root, inbox = _inbox(tmp_path)
    source = inbox / "syllabus.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as output:
        writer.write(output)
    before = source.read_bytes()

    result = preview_file(source, workspace_root=root, semester="Fall 2026")

    assert result["kind"] == "pdf"
    assert result["name"] == "syllabus.pdf"
    assert isinstance(result["content"], str)
    assert source.read_bytes() == before


def test_docx_and_pptx_previews_extract_visible_text(tmp_path: Path) -> None:
    root, inbox = _inbox(tmp_path)
    docx = inbox / "notes.docx"
    pptx = inbox / "slides.pptx"
    with ZipFile(docx, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<document><body><p><t>Document note</t></p></body></document>")
    with ZipFile(pptx, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ppt/slides/slide1.xml", "<slide><text><t>Slide title</t><t>Slide detail</t></text></slide>")

    docx_result = preview_file(docx, workspace_root=root, semester="Fall 2026")
    pptx_result = preview_file(pptx, workspace_root=root, semester="Fall 2026")

    assert docx_result["content"] == "Document note"
    assert pptx_result["content"] == "Slide title\nSlide detail"


def test_preview_rejects_files_outside_the_active_semester_library(tmp_path: Path) -> None:
    root, inbox = _inbox(tmp_path)
    outside = tmp_path / "private-notes.md"
    outside.write_text("must not be served", encoding="utf-8")

    with pytest.raises(FilePreviewError):
        preview_file(outside, workspace_root=root, semester="Fall 2026")

    hidden_state = root / ".academia" / "secret.md"
    hidden_state.parent.mkdir(parents=True)
    hidden_state.write_text("operational state", encoding="utf-8")
    with pytest.raises(FilePreviewError):
        preview_file(hidden_state, workspace_root=root, semester="Fall 2026")

    assert inbox.is_dir()
