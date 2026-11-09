from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from academia_os.extraction import ExtractionStatus, extract_source_document, extract_syllabus


SYLLABUS = """# POL 3124 - Politics and Society

Course: POL 3124 - Politics and Society

## Assessments
- Research Essay — 25% — Due October 19, 2026
- Midterm Exam — 30% — Due November 2, 2026
- Participation — 10%
- Reflection Paper — Due near midterm period

## Required Readings
- Smith, John. Politics Today, 3rd ed., Chapter 2, pp. 10-20
- Doe, Jane. Institutions and Power (2024), ISBN 978-1234567890

## Course Meetings
- Monday 10:00 AM - 11:30 AM, Room 201
- Wednesday 10:00 AM - 11:30 AM, Room 201
"""


def test_markdown_source_extraction_preserves_segments_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "POL3124_Syllabus.md"
    path.write_text(SYLLABUS, encoding="utf-8")

    document = extract_source_document(path)
    repeated = extract_source_document(path)

    assert document.status is ExtractionStatus.SUPPORTED
    assert document.media_type == "text/markdown"
    assert document.extraction_method == "utf-8-text"
    assert document.content_hash == repeated.content_hash
    assert any(segment.section == "Assessments" and segment.start_line for segment in document.segments)
    assert any("Research Essay" in segment.text for segment in document.segments)


def test_plain_text_syllabus_extraction_preserves_line_locations(tmp_path: Path) -> None:
    path = tmp_path / "syllabus.txt"
    path.write_text("Course: POL 3124 - Politics\nDue October 19, 2026\n", encoding="utf-8")

    document = extract_source_document(path)

    assert document.media_type == "text/plain"
    assert document.segments[0].start_line == 1
    assert document.segments[1].source_location == "line 2"


def test_syllabus_candidates_extract_supported_facts_with_direct_evidence(tmp_path: Path) -> None:
    path = tmp_path / "POL3124_Syllabus.md"
    path.write_text(SYLLABUS, encoding="utf-8")

    result = extract_syllabus(path, course_id="POL 3124 - Politics and Society", verified_current=True)

    assignments = [candidate for candidate in result.candidates if candidate.kind == "assignment"]
    deadlines = [candidate for candidate in result.candidates if candidate.kind == "deadline"]
    readings = [candidate for candidate in result.candidates if candidate.kind == "required_reading"]
    meetings = [candidate for candidate in result.candidates if candidate.kind == "course_meeting"]
    sources = [candidate for candidate in result.candidates if candidate.kind == "course_identity"]

    essay = next(candidate for candidate in assignments if candidate.entity["title"] == "Research Essay")
    assert essay.entity["weight"] == "25%"
    assert essay.entity["deadline"] == "2026-10-19"
    assert essay.confidence == "current-confirmed"
    assert essay.evidence.source == path.name
    assert essay.evidence.source_path == str(path.resolve())
    assert essay.evidence.source_location == "line 6"
    assert essay.evidence.reference["segment"] == 5
    assert essay.evidence.excerpt and "Research Essay" in essay.evidence.excerpt
    assert len(deadlines) == 2
    assert len(readings) == 2
    assert len(meetings) == 2
    assert sources[0].entity["course_id"] == "POL 3124 - Politics and Society"


def test_syllabus_course_identity_mismatch_is_unverified(tmp_path: Path) -> None:
    path = tmp_path / "wrong-course.md"
    path.write_text("Course: POL 9999 - Other Course\n## Assessments\n- Essay — 20% — Due October 19, 2026\n", encoding="utf-8")

    result = extract_syllabus(path, course_id="POL 3124 - Politics", verified_current=True)

    assert result.identity_status == "mismatch"
    assert all(candidate.confidence == "unverified" for candidate in result.candidates)
    assert any("does not match" in warning for warning in result.warnings)


def test_syllabus_missing_values_stay_null_and_ambiguous_dates_are_not_confirmed(tmp_path: Path) -> None:
    path = tmp_path / "syllabus.md"
    path.write_text(
        "## Assessments\n- Reflection Paper — 15%\n- Essay — Due near midterm period\n",
        encoding="utf-8",
    )

    result = extract_syllabus(path, course_id="POL 3124")
    assignments = {candidate.entity["title"]: candidate for candidate in result.candidates if candidate.kind == "assignment"}

    assert assignments["Reflection Paper"].entity["deadline"] is None
    assert assignments["Reflection Paper"].entity["weight"] == "15%"
    assert assignments["Essay"].entity["deadline"] is None
    assert assignments["Essay"].confidence != "current-confirmed"
    assert any("ambiguous" in warning.lower() for warning in result.warnings)


def test_scanned_pdf_returns_unsupported_without_ocr(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buffer = io.BytesIO()
    writer.write(buffer)
    path.write_bytes(buffer.getvalue())

    document = extract_source_document(path)

    assert document.status is ExtractionStatus.UNSUPPORTED_WITHOUT_OCR
    assert "unsupported_without_ocr" in document.unsupported
    assert document.segments == ()


def test_text_pdf_preserves_page_references(tmp_path: Path) -> None:
    path = tmp_path / "text.pdf"
    path.write_bytes(base64.b64decode("JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDMwMCAzMDBdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEwMC9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNoVyLEKwlAMBdA9X5E/MMnNSyiUDkIXNyGbOEj14dAOXfz+Ws52aKdrkbL8KaexinBtdPl+1h+rcnV+jI7o2dIS0fAyaeLdFxMACoOb2Pvc6LHEkB5DIDE960Zz0Z0OhUgW4AplbmRzdHJlYW0KZW5kb2JqCgp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwNDIgMDAwMDAgbiAKMDAwMDAwMDEyMCAwMDAwMCBuIAowMDAwMDAwMTcyIDAwMDAwIG4gCjAwMDAwMDAyMTMgMDAwMDAgbiAKMDAwMDAwMDMyMCAwMDAwMCBuIAowMDAwMDAwNDA5IDAwMDAwIG4gCgp0cmFpbGVyCjw8L1NpemUgNy9Sb290IDEgMCBSL0lEWzwwRTE3QzM5RjBCQzNCOTMxMDY1MUMzQUI1QTJDQzI4Nj48NDQ3N0JEMkY5QTk4RTZDMDhCQzQ1RkJGM0I1ODU3MzE+XT4+CnN0YXJ0eHJlZgo1NzgKJSVFT0YK"))

    document = extract_source_document(path)

    assert document.status is ExtractionStatus.SUPPORTED
    assert document.segments[0].page == 1
    assert document.segments[0].source_location == "page 1"
    assert "POL 3124" in document.segments[0].text


def test_docx_assessments_use_term_year_and_preserve_split_runs(tmp_path: Path) -> None:
    from zipfile import ZipFile
    path = tmp_path / "syllabus.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>LSR 1100-A00</w:t></w:r></w:p>
        <w:p><w:r><w:t>Session: Fall 20</w:t></w:r><w:r><w:t>26</w:t></w:r></w:p>
        <w:p><w:r><w:t>October 15 LECTURE 6: The Concept of Play</w:t></w:r></w:p>
        <w:p><w:r><w:t>QUIZ 1 AT 9:00PM (ON ALL READINGS OF OCTOBER 15 ONLY)</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>QUIZ 1 (OCTOBER 15)</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>10%</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        <w:p><w:r><w:t>FINAL EXAM (DATE TO BE DETERMINED) 30%</w:t></w:r></w:p>
        </w:body></w:document>""")
    result = extract_syllabus(path, course_id="LSR 1100-A00")
    assert result.identity_status == "matched"
    assignments = [c for c in result.candidates if c.entity_type == "assignment"]
    deadlines = [c for c in result.candidates if c.entity_type == "deadline"]
    assert len(assignments) == 2
    assert len(deadlines) == 1
    assert deadlines[0].entity["date"] == "2026-10-15"
    assert deadlines[0].entity["time"] == "21:00"
    assert assignments[0].entity["weight"] == "10%"
    assert assignments[1].entity["deadline"] is None
    assert deadlines[0].confidence == "likely"
    assert deadlines[0].evidence.source_location.startswith("line ")


def test_pdf_assessment_lines_merge_table_and_prose_without_page_sized_tasks() -> None:
    from academia_os.extraction.models import SourceDocument, SourceSegment
    from academia_os.extraction.syllabus import _formatted_assessments
    document = SourceDocument("syllabus.pdf", "application/pdf", (
        SourceSegment("POL2108A\nFall Term 2026", page=1),
        SourceSegment("First Essay (mandatory) 25% October 8\nSecond Essay (mandatory) 25% November 12\nFinal Exam (mandatory) 30% TBA", page=3),
        SourceSegment("Essay One (due October 8th at 2:30 p.m.) should be 4-6 pages. Essay Two (due November 12 at 2:30 p.m.) should be 6-8 pages.\nLate essays will be penalized 5 percent per day.", page=4),
    ), "pypdf-text", "hash")
    candidates, warnings = _formatted_assessments(document, "POL2108A", False)
    deadlines = {c.entity["title"]: c for c in candidates if c.entity_type == "deadline"}
    assert len([c for c in candidates if c.entity_type == "assignment"]) == 3
    assert deadlines["First Essay"].entity["date"] == "2026-10-08"
    assert deadlines["First Essay"].entity["time"] == "14:30"
    assert deadlines["First Essay"].evidence.source_location == "page 4"
    assert deadlines["Second Essay"].entity["date"] == "2026-11-12"
    assert not warnings


def test_formatted_syllabus_without_term_year_does_not_invent_dates() -> None:
    from academia_os.extraction.models import SourceDocument, SourceSegment
    from academia_os.extraction.syllabus import _formatted_assessments
    document = SourceDocument("syllabus.pdf", "application/pdf", (SourceSegment("First Essay 25% October 8", page=1),), "pypdf-text", "hash")
    candidates, warnings = _formatted_assessments(document, "POL2108A", True)
    assert len(candidates) == 1
    assert candidates[0].entity["deadline"] is None
    assert candidates[0].confidence == "unverified"
    assert warnings
