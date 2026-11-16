"""Bounded local OCR for scanned PDF pages with a bundled PDF renderer."""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from . import macos_vision
from .processing import cache_signature
from .state import JsonStateStore

OCR_PAGE_TIMEOUT_SECONDS = 20
OCR_DPI = 160
TIME_LIMIT_NOTICE = "Local OCR reached its time limit; some scanned pages were not processed."
# PDFium is not thread-safe; the dashboard handles chat requests on threads.
_PDFIUM_LOCK = threading.Lock()

try:  # Declared in pyproject; keep this module importable in bare checkouts.
    import pypdfium2 as _pdfium
except ImportError:  # pragma: no cover - only when the dependency is absent
    _pdfium = None


def _write_png(path: Path, *, width: int, height: int, stride: int, pixels: bytes) -> None:
    """Write one RGB PNG without an imaging dependency.

    OCR binarizes the page, so the renderer's RGB channel order and silence on
    colour management do not affect recognition.
    """
    if width <= 0 or height <= 0 or stride < width * 3 or len(pixels) < stride * height:
        raise ValueError("unexpected PDF page bitmap")

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    rows = bytearray()
    for row in range(height):
        start = row * stride
        rows.append(0)
        rows += pixels[start:start + width * 3]
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def _render_pdf_page(document: Any, page_number: int, target: Path) -> None:
    """Rasterize one 1-based PDF page beside ``target`` without Poppler."""
    with _PDFIUM_LOCK:
        try:
            page = document[page_number - 1]
        except Exception as exc:  # pdfium raises for out-of-range or damaged pages
            raise RuntimeError(f"PDF page {page_number} could not be opened") from exc
        try:
            bitmap = page.render(scale=OCR_DPI / 72, rev_byteorder=True)
            try:
                if _pdfium is None or bitmap.format != _pdfium.raw.FPDFBitmap_BGR:
                    raise RuntimeError("unexpected PDF page format")
                width, height, stride = bitmap.width, bitmap.height, bitmap.stride
                pixels = bytes(bitmap.buffer)
            finally:
                bitmap.close()
        finally:
            page.close()
    try:
        _write_png(target, width=width, height=height, stride=stride, pixels=pixels)
    except (OSError, ValueError) as exc:
        raise RuntimeError("PDF page could not be encoded") from exc


def _cache_key(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _read_cache(root: Path, path: Path, digest: str | None) -> dict[int, str]:
    key = _cache_key(root, path)
    if key is None or not digest:
        return {}
    state = JsonStateStore(root / ".academia" / "extracted_sources.json").read({"records": {}})
    records = state.get("records", {}) if isinstance(state, dict) else {}
    record = records.get(key) if isinstance(records, dict) else None
    if not isinstance(record, dict) or record.get("ocr_sha256") != digest:
        return {}
    pages = record.get("ocr_pages")
    if not isinstance(pages, dict):
        return {}
    result: dict[int, str] = {}
    for number, text in pages.items():
        try:
            page = int(number)
        except (TypeError, ValueError):
            continue
        if page > 0 and isinstance(text, str) and text.strip():
            result[page] = text
    return result


def _write_cache(root: Path, path: Path, digest: str | None, pages: dict[int, str]) -> None:
    key = _cache_key(root, path)
    if key is None or not digest or not pages:
        return
    try:
        signature = cache_signature(path)
    except OSError:
        return
    store = JsonStateStore(root / ".academia" / "extracted_sources.json")

    def save(raw: Any) -> Any:
        state = raw if isinstance(raw, dict) else {"schema_version": 1, "records": {}}
        records = state.get("records")
        if not isinstance(records, dict):
            records = {}
        old = records.get(key)
        record = old if isinstance(old, dict) and old.get("signature") == signature else {"signature": signature}
        existing = record.get("ocr_pages") if record.get("ocr_sha256") == digest else {}
        combined = dict(existing) if isinstance(existing, dict) else {}
        combined.update({str(number): text for number, text in pages.items()})
        record["ocr_sha256"] = digest
        record["ocr_pages"] = combined
        records[key] = record
        state["schema_version"] = 1
        state["records"] = records
        return state

    store.update({"schema_version": 1, "records": {}}, save)


def ocr_pdf_pages(
    path: Path,
    page_numbers: list[int],
    *,
    cache_root: Path | None = None,
    digest: str | None = None,
    max_pages: int | None = None,
    max_seconds: float = 120,
    write_cache: bool = True,
) -> tuple[dict[int, str], int, list[int], list[str]]:
    """OCR blank PDF pages locally, returning text, attempts, skipped pages, and notices.

    Text is cached in Academia's rebuildable extracted-source index when the PDF is
    inside the configured workspace. The original PDF is never modified.
    """
    requested = list(dict.fromkeys(page for page in page_numbers if page > 0))
    cached = _read_cache(cache_root, path, digest) if cache_root is not None else {}
    result = {page: cached[page] for page in requested if page in cached}
    pending = [page for page in requested if page not in cached]
    if max_pages is not None and len(pending) > max_pages:
        skipped = pending[max_pages:]
        pending = pending[:max_pages]
    else:
        skipped = []
    if not pending:
        notices = [f"OCR page limit reached; {len(skipped)} scanned page(s) were not processed."] if skipped else []
        return result, 0, skipped, notices

    engine = os.environ.get("ACADEMIA_OCR_ENGINE", "").strip().casefold()
    recognizer = None if engine == "vision" else shutil.which("tesseract")
    vision_available = engine != "tesseract" and macos_vision.available()
    if _pdfium is None or (recognizer is None and not vision_available):
        skipped.extend(pending)
        if _pdfium is None:
            missing = "the bundled PDF renderer is unavailable; reinstall Academia OS"
        elif engine == "tesseract":
            missing = "Tesseract is not installed"
        else:
            missing = "no local OCR engine is available; install Tesseract or use macOS"
        return result, 0, skipped, [f"Local PDF OCR is unavailable because {missing}."]

    deadline = time.monotonic() + max(0, max_seconds)
    attempted = 0
    notices: list[str] = []
    newly_extracted: dict[int, str] = {}
    try:
        with _PDFIUM_LOCK:
            document = _pdfium.PdfDocument(str(path))
    except Exception:
        skipped.extend(pending)
        return result, 0, skipped, ["This PDF could not be opened for local OCR."]
    try:
        with tempfile.TemporaryDirectory(prefix="academia-pdf-ocr-") as temporary:
            folder = Path(temporary)
            rendered: list[tuple[int, Path]] = []
            for index, page in enumerate(pending):
                if deadline - time.monotonic() <= 0:
                    skipped.extend(pending[index:])
                    notices.append(TIME_LIMIT_NOTICE)
                    break
                image = folder / f"page-{page}.png"
                try:
                    _render_pdf_page(document, page, image)
                except RuntimeError:
                    skipped.append(page)
                    notices.append(f"Local OCR could not process PDF page {page}.")
                    continue
                rendered.append((page, image))
            if recognizer is not None:
                for page, image in rendered:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        skipped.append(page)
                        notices.append(TIME_LIMIT_NOTICE)
                        continue
                    try:
                        recognized = subprocess.run(
                            [recognizer, str(image), "stdout", "-l", "eng", "--psm", "3"],
                            capture_output=True,
                            text=True,
                            timeout=min(OCR_PAGE_TIMEOUT_SECONDS, remaining),
                            check=False,
                        )
                        if recognized.returncode != 0:
                            raise RuntimeError("text recognition failed")
                        text = recognized.stdout.strip()
                        attempted += 1
                        if text:
                            result[page] = text
                            newly_extracted[page] = text
                    except (OSError, subprocess.TimeoutExpired, RuntimeError):
                        skipped.append(page)
                        attempted += 1
                        notices.append(f"Local OCR could not process PDF page {page}.")
            elif rendered:
                # macOS Vision recognizes the whole rendered batch in one call.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    skipped.extend(page for page, _ in rendered)
                    notices.append(TIME_LIMIT_NOTICE)
                else:
                    texts = macos_vision.recognize([image for _, image in rendered], timeout=remaining)
                    if texts is None:
                        skipped.extend(page for page, _ in rendered)
                        notices.append("Local OCR could not run macOS Vision on the rendered pages.")
                    else:
                        for (page, _), text in zip(rendered, texts):
                            attempted += 1
                            cleaned = text.strip()
                            if cleaned:
                                result[page] = cleaned
                                newly_extracted[page] = cleaned
    finally:
        with _PDFIUM_LOCK:
            document.close()

    if write_cache and cache_root is not None:
        try:
            _write_cache(cache_root, path, digest, newly_extracted)
        except OSError:
            notices.append("OCR succeeded, but its rebuildable local text cache could not be saved.")
    if skipped and not any("time limit" in notice for notice in notices):
        skipped = list(dict.fromkeys(skipped))
        if not notices:
            notices.append(f"OCR could not process {len(skipped)} scanned page(s).")
    return result, attempted, skipped, list(dict.fromkeys(notices))
