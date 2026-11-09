"""Bounded local OCR for scanned PDF pages using installed system tools."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .processing import cache_signature
from .state import JsonStateStore

OCR_PAGE_TIMEOUT_SECONDS = 20
OCR_DPI = 160


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

    renderer = shutil.which("pdftoppm")
    recognizer = shutil.which("tesseract")
    if not renderer or not recognizer:
        skipped.extend(pending)
        missing = " and ".join(name for name, found in (("Poppler pdftoppm", renderer), ("Tesseract", recognizer)) if not found)
        return result, 0, skipped, [f"Local PDF OCR is unavailable because {missing} is not installed."]

    deadline = time.monotonic() + max(0, max_seconds)
    attempted = 0
    notices: list[str] = []
    newly_extracted: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="academia-pdf-ocr-") as temporary:
        folder = Path(temporary)
        for page in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                skipped.extend(pending[attempted:])
                notices.append("Local OCR reached its time limit; some scanned pages were not processed.")
                break
            prefix = folder / f"page-{page}"
            try:
                rendered = subprocess.run(
                    [renderer, "-f", str(page), "-l", str(page), "-r", str(OCR_DPI), "-png", "-singlefile", str(path), str(prefix)],
                    capture_output=True,
                    text=True,
                    timeout=min(OCR_PAGE_TIMEOUT_SECONDS, remaining),
                    check=False,
                )
                image = prefix.with_suffix(".png")
                if rendered.returncode != 0 or not image.is_file():
                    raise RuntimeError("PDF page rendering failed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    skipped.append(page)
                    skipped.extend(pending[attempted + 1:])
                    notices.append("Local OCR reached its time limit; some scanned pages were not processed.")
                    break
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

    if cache_root is not None:
        try:
            _write_cache(cache_root, path, digest, newly_extracted)
        except OSError:
            notices.append("OCR succeeded, but its rebuildable local text cache could not be saved.")
    if skipped and not any("time limit" in notice for notice in notices):
        skipped = list(dict.fromkeys(skipped))
        if not notices:
            notices.append(f"OCR could not process {len(skipped)} scanned page(s).")
    return result, attempted, skipped, list(dict.fromkeys(notices))
