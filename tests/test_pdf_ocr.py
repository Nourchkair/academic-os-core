from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfWriter

from academia_os import pdf_ocr


def blank_pdf(path: Path) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as output:
        writer.write(output)
    return path


def test_ocr_pdf_pages_renders_with_the_bundled_pdf_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    checked: dict[str, Any] = {}

    def fake_which(name: str) -> str | None:
        checked.setdefault("tools", []).append(name)
        return "/fake/tesseract" if name == "tesseract" else None

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        image = Path(command[1])
        checked["command"] = command
        checked["png"] = image.read_bytes()[:8]
        checked["png_size"] = image.stat().st_size
        return SimpleNamespace(returncode=0, stdout="Recovered scan text", stderr="")

    monkeypatch.setattr(pdf_ocr.shutil, "which", fake_which)
    monkeypatch.setattr(pdf_ocr.subprocess, "run", fake_run)

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=2, max_seconds=30)

    assert text == {1: "Recovered scan text"}
    assert attempted == 1
    assert skipped == []
    assert notices == []
    assert checked["command"][0] == "/fake/tesseract"
    assert checked["png"] == b"\x89PNG\r\n\x1a\n"
    assert checked["png_size"] > 0
    assert "pdftoppm" not in checked["tools"]


def test_ocr_pdf_pages_reports_a_missing_renderer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr(pdf_ocr, "_pdfium", None)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: "/fake/tesseract")

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1, 2], max_pages=5, max_seconds=30)

    assert text == {}
    assert attempted == 0
    assert skipped == [1, 2]
    assert "bundled PDF renderer" in notices[0]


def test_ocr_pdf_pages_falls_back_to_macos_vision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    seen: dict[str, Any] = {}

    def fake_recognize(paths: list[Path], *, timeout: float) -> list[str]:
        seen["paths"] = [Path(path) for path in paths]
        seen["png"] = Path(paths[0]).read_bytes()[:8]
        return ["Vision recovered text"]

    monkeypatch.delenv("ACADEMIA_OCR_ENGINE", raising=False)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_ocr.macos_vision, "available", lambda: True)
    monkeypatch.setattr(pdf_ocr.macos_vision, "recognize", fake_recognize)

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=2, max_seconds=30)

    assert text == {1: "Vision recovered text"}
    assert attempted == 1
    assert skipped == []
    assert notices == []
    assert seen["png"] == b"\x89PNG\r\n\x1a\n"


def test_ocr_pdf_pages_reports_vision_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.delenv("ACADEMIA_OCR_ENGINE", raising=False)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_ocr.macos_vision, "available", lambda: True)
    monkeypatch.setattr(pdf_ocr.macos_vision, "recognize", lambda paths, *, timeout: None)

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=2, max_seconds=30)

    assert text == {}
    assert attempted == 0
    assert skipped == [1]
    assert "macOS Vision" in notices[0]


def test_ocr_pdf_pages_reports_missing_ocr_engines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.delenv("ACADEMIA_OCR_ENGINE", raising=False)
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_ocr.macos_vision, "available", lambda: False)

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=5, max_seconds=30)

    assert text == {}
    assert attempted == 0
    assert skipped == [1]
    assert "no local OCR engine" in notices[0]


def test_ocr_pdf_pages_skips_unreadable_pages_with_a_notice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = blank_pdf(tmp_path / "scan.pdf")
    monkeypatch.setattr(pdf_ocr.shutil, "which", lambda name: "/fake/tesseract")

    def failing_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="recognition failed")

    monkeypatch.setattr(pdf_ocr.subprocess, "run", failing_run)

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=5, max_seconds=30)

    assert text == {}
    assert attempted == 1
    assert skipped == [1]
    assert "could not process PDF page 1" in notices[0]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_ocr_pdf_pages_recognizes_a_rendered_page_end_to_end(tmp_path: Path) -> None:
    source = blank_pdf(tmp_path / "blank.pdf")

    text, attempted, skipped, notices = pdf_ocr.ocr_pdf_pages(source, [1], max_pages=2, max_seconds=60)

    assert attempted == 1
    assert skipped == []
    assert notices == []
    assert text == {}
