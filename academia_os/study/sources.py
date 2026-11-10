"""Bounded course retrieval. Citations identify exact local source versions."""
from __future__ import annotations

import hashlib
import heapq
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..course_identity import resolve_course_directory
from ..file_preview import PREVIEW_EXTENSIONS, read_office_text
from ..library import list_material
from ..pdf_ocr import ocr_pdf_pages

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_DEEP_SOURCES = 300
MAX_DEEP_TEXT_CHARS = 64_000_000
MAX_DEEP_CHUNKS = 128
MAX_STUDY_OCR_PAGES = 180
MAX_STUDY_OCR_SECONDS = 180
CHUNK_SIZE = 1200
SEARCH_STOP_WORDS = {
    'about', 'after', 'again', 'also', 'and', 'are', 'because', 'been', 'before', 'being', 'between',
    'as', 'at', 'be', 'but', 'by', 'can', 'could', 'did', 'does', 'for', 'from', 'have', 'help', 'how', 'if', 'in', 'into', 'is', 'it', 'its', 'just',
    'like', 'make', 'me', 'more', 'most', 'my', 'not', 'of', 'on', 'or', 'our', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their',
    'them', 'then', 'there', 'these', 'they', 'this', 'those', 'through', 'to', 'up', 'want', 'was', 'we', 'were', 'what', 'when',
    'where', 'which', 'with', 'would', 'you', 'your',
}


def safe_path(root: Path, path: Path) -> Path:
    root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("source must be inside this workspace") from exc
    current = root
    for part in relative.parts:
        if part in {"..", ".academia"} or part.startswith('.'):
            raise ValueError("hidden or parent paths are not study sources")
        current = current / part
        if current.is_symlink():
            raise ValueError("study paths cannot traverse symbolic links")
    candidate.resolve().relative_to(root)
    return candidate


def fingerprint(path: Path) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("study sources must be at most 64 MB; split a larger textbook first")
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def catalog(root: Path, semester: str, course: str) -> list[dict[str, Any]]:
    directory = resolve_course_directory(root, semester, course)
    return [item for item in list_material(root, semester)
            if item['course_id'] == directory.name and item['extension'] in PREVIEW_EXTENSIONS
            and '/STUDY/' not in item['relative_path']]


def _segments(
    path: Path,
    pages: str | None,
    *,
    deep: bool = False,
    workspace_root: Path | None = None,
    digest: str | None = None,
    ocr_budget: int | None = None,
    ocr_seconds: float = MAX_STUDY_OCR_SECONDS,
) -> tuple[list[tuple[str, str, bool]], bool, int | None, int | None, int, list[str]]:
    if path.suffix.lower() == '.pdf':
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        start, end = 1, page_count if deep else min(page_count, 100)
        if pages:
            match = re.fullmatch(r'(\d+)(?:-(\d+))?', pages)
            if not match:
                raise ValueError("pages must be a 1-based page or range, such as 12-25")
            start, end = int(match[1]), int(match[2] or match[1])
            if start < 1 or end < start or end > page_count or end - start >= 100:
                raise ValueError("select an existing range of at most 100 PDF pages")
        segments: list[tuple[str, str, bool]] = []
        total = 0
        text_was_truncated = False
        empty_pages: list[int] = []
        page_texts: dict[int, str] = {}
        for index in range(start - 1, end):
            text = reader.pages[index].extract_text() or ''
            if text.strip():
                page_texts[index + 1] = text
            else:
                empty_pages.append(index + 1)
        recognized: dict[int, str] = {}
        ocr_attempted = 0
        ocr_skipped: list[int] = []
        ocr_notices: list[str] = []
        if empty_pages:
            recognized, ocr_attempted, ocr_skipped, ocr_notices = ocr_pdf_pages(
                path,
                empty_pages,
                cache_root=workspace_root,
                digest=digest,
                max_pages=ocr_budget,
                max_seconds=ocr_seconds,
            )
        for index in range(start - 1, end):
            page_number = index + 1
            text = page_texts.get(page_number, '')
            is_ocr = False
            if not text.strip():
                text = recognized.get(page_number, '')
                is_ocr = bool(text.strip())
            remaining = (MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS) - total
            if remaining <= 0:
                break
            segments.append((f'page {page_number}', text[:remaining], is_ocr))
            if len(text) > remaining:
                text_was_truncated = True
            total += len(text)
            if total >= (MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS):
                break
        scanned_pages = len(segments)
        cap = MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS
        truncated = (
            start > 1 or end < page_count or scanned_pages < end - start + 1 or text_was_truncated
            or bool(ocr_skipped) or (total >= cap and start - 1 + scanned_pages < end)
        )
        return segments, truncated, scanned_pages, page_count, ocr_attempted, ocr_notices
    if pages:
        raise ValueError("page selection is supported for PDFs only")
    if path.suffix.lower() in {'.docx', '.pptx'}:
        text, truncated = read_office_text(path, path.suffix.lower(), max_chars=MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS)
    else:
        with path.open('r', encoding='utf-8', errors='replace') as handle:
            text = handle.read((MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS) + 1)
        cap = MAX_DEEP_TEXT_CHARS if deep else MAX_TEXT_CHARS
        truncated = len(text) > cap
        text = text[:cap]
    return [('text', text, False)], truncated, None, None, 0, []


def retrieve(root: Path, semester: str, course: str, *, source_ids: list[str] | None = None,
             query: str = '', pages: str | None = None, limit: int = 12, deep: bool = False) -> dict[str, Any]:
    directory = resolve_course_directory(root, semester, course)
    max_chunks = MAX_DEEP_CHUNKS if deep else 24
    if not 1 <= limit <= max_chunks:
        raise ValueError(f"study context limit must be between 1 and {max_chunks}")
    available = catalog(root, semester, directory.name)
    # No source body is retrieved unless explicitly selected or a search is requested.
    if not source_ids and not query.strip():
        return {'course_id': directory.name, 'semester': semester, 'sources': available, 'chunks': [],
                'warnings': ['Select source IDs or enter a topic to retrieve excerpts.']}
    selected = [item for item in available if item['id'] in (source_ids or [])]
    if source_ids and len({item['id'] for item in selected}) != len(set(source_ids)):
        raise ValueError("every study source must belong to this course's Library")
    if deep and len(selected) > MAX_DEEP_SOURCES:
        raise ValueError(f"deep study search supports at most {MAX_DEEP_SOURCES} selected sources per class")
    if not deep and len(selected) > 12:
        raise ValueError("select at most 12 study sources per request")
    if not source_ids:
        selected = available[:MAX_DEEP_SOURCES if deep else 12]
    terms = set(re.findall(r'[a-z0-9]{2,}', query.casefold())) - SEARCH_STOP_WORDS
    heap: list[tuple[int, int, dict[str, Any]]] = []
    unranked_chunks: list[dict[str, Any]] = []
    sample_counts: dict[str, int] = {}
    warnings, sources = [], []
    matching_count = 0
    scanned_chunk_count = 0
    sequence = 0
    ocr_page_budget = MAX_STUDY_OCR_PAGES
    ocr_deadline = time.monotonic() + MAX_STUDY_OCR_SECONDS
    available_count = len(available)
    if not source_ids and available_count > (MAX_DEEP_SOURCES if deep else 12):
        if deep:
            warnings.append(f"Deep topic search examined the first {MAX_DEEP_SOURCES} course sources; narrow the class selection to search beyond that set.")
        else:
            warnings.append('Topic search examined the first 12 course sources. Select specific Library IDs to search other material.')
    for item in selected:
        path = safe_path(root, Path(item['path']))
        try:
            digest = fingerprint(path)
            segments, truncated, pages_scanned, page_count, ocr_attempted, ocr_notices = _segments(
                path,
                pages,
                deep=deep,
                workspace_root=root,
                digest=digest,
                ocr_budget=ocr_page_budget,
                ocr_seconds=max(0, ocr_deadline - time.monotonic()),
            )
            ocr_page_budget = max(0, ocr_page_budget - ocr_attempted)
        except (OSError, ValueError) as exc:
            if pages and isinstance(exc, ValueError):
                raise
            warnings.append(f"{item['name']}: {exc}")
            continue
        except Exception:
            warnings.append(f"{item['name']}: text extraction failed; use an accessible text copy.")
            continue
        ocr_pages = sum(1 for _location, text, is_ocr in segments if is_ocr and text.strip())
        sources.append({**item, 'sha256': digest, 'pages_scanned': pages_scanned, 'page_count': page_count,
                        'ocr_pages': ocr_pages,
                        'complete': not truncated})
        warnings.extend(f"{item['name']}: {notice}" for notice in ocr_notices)
        if truncated:
            if deep:
                warnings.append(f"{item['name']}: deep reading stopped at the extraction bound; some content was not searched.")
            else:
                warnings.append(f"{item['name']}: only a bounded excerpt was searched; use page ranges for other chapters.")
        found = False
        for location, text, is_ocr in segments:
            for offset in range(0, len(text), CHUNK_SIZE):
                excerpt = text[offset:offset + CHUNK_SIZE].strip()
                if not excerpt:
                    continue
                scanned_chunk_count += 1
                found = True
                locator = f'{location} · characters {offset + 1}-{min(offset + CHUNK_SIZE, len(text))}'
                chunk_id = hashlib.sha256(f"{item['id']}:{digest}:{locator}".encode()).hexdigest()[:24]
                chunk = {'id': chunk_id, 'source_id': item['id'], 'source_name': item['name'],
                         'locator': locator, 'text': excerpt, 'sha256': digest,
                         'ocr': is_ocr,
                         'provenance': item.get('provenance'), 'authoritative': item.get('authoritative')}
                if terms:
                    token_counts = Counter(re.findall(r'[a-z0-9]{2,}', excerpt.casefold()))
                    score = sum(min(token_counts[term], 5) * (2 if len(term) <= 2 else 1) for term in terms)
                    if score:
                        matching_count += 1
                        if deep:
                            sequence += 1
                            entry = (score, sequence, {**chunk, '_score': score})
                            if len(heap) < limit:
                                heapq.heappush(heap, entry)
                            elif entry[:2] > heap[0][:2]:
                                heapq.heapreplace(heap, entry)
                        else:
                            unranked_chunks.append({**chunk, '_score': score})
                elif deep:
                    # With no searchable terms, keep a small sample from every selected source.
                    if sample_counts.get(item['id'], 0) < max(1, limit // max(1, len(selected))):
                        unranked_chunks.append(chunk)
                        sample_counts[item['id']] = sample_counts.get(item['id'], 0) + 1
                else:
                    unranked_chunks.append(chunk)
        if not found:
            warnings.append(f"{item['name']}: no readable text was found, including after local OCR.")
    if deep and terms:
        unranked_chunks = [entry[2] for entry in sorted(heap, key=lambda entry: (-entry[0], entry[1]))]
    elif terms:
        unranked_chunks.sort(key=lambda chunk: -chunk['_score'])
    elif len(sources) > 1:
        grouped = [[chunk for chunk in unranked_chunks if chunk['source_id'] == item['id']] for item in sources]
        unranked_chunks = [group[index] for index in range(max(map(len, grouped), default=0)) for group in grouped if index < len(group)]
    total = matching_count if terms else scanned_chunk_count
    chunks = [{key: value for key, value in chunk.items() if key != '_score'} for chunk in unranked_chunks[:limit]]
    coverage = {
        'deep': deep,
        'selected_sources': len(selected),
        'scanned_sources': len(sources),
        'complete': len(sources) == len(selected) and all(source['complete'] for source in sources) and not warnings,
        'pdf_pages_scanned': sum(source.get('pages_scanned') or 0 for source in sources),
        'ocr_pages_scanned': sum(source.get('ocr_pages') or 0 for source in sources),
        'matching_chunks': total,
        'returned_chunks': len(chunks),
    }
    return {'course_id': directory.name, 'semester': semester, 'sources': sources,
            'chunks': chunks, 'matching_chunk_count': total, 'truncated': total > limit, 'warnings': warnings,
            'coverage': coverage}
