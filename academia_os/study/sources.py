"""Bounded course retrieval. Citations identify exact local source versions."""
from __future__ import annotations

import hashlib
import heapq
import os
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..course_identity import resolve_course_directory
from ..file_preview import PREVIEW_EXTENSIONS, read_office_text
from ..library import list_material
from ..pdf_ocr import ocr_pdf_pages
from ..processing import cache_signature
from ..state import JsonStateStore

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_DEEP_SOURCES = 300
MAX_DEEP_TEXT_CHARS = 64_000_000
MAX_DEEP_CHUNKS = 128
MAX_STUDY_OCR_PAGES = 180
MAX_STUDY_OCR_SECONDS = 180
MAX_EXTRACTION_WORKERS = 4
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


_CACHE_INCOMPLETE_MARKERS = (
    'incomplete', 'did not extract', 'truncated', 'was not searched',
    'no readable text', 'could not process', 'unavailable',
)


def _cache_state(root: Path) -> dict[str, Any]:
    """Read the rebuildable extraction cache once per retrieval call."""

    try:
        state = JsonStateStore(root / '.academia' / 'extracted_sources.json').read({'records': {}})
    except (OSError, ValueError):
        return {}
    records = state.get('records') if isinstance(state, dict) else None
    return records if isinstance(records, dict) else {}


def _cached_pdf(
    root: Path,
    path: Path,
    records: dict[str, Any],
) -> tuple[str, list[tuple[str, str, bool]], bool, int, None, int, list[str]] | None:
    """Return cached PDF text without re-parsing the file, when the cache is current."""

    if path.suffix.lower() != '.pdf':
        return None
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        signature = cache_signature(path)
    except (OSError, ValueError):
        return None
    record = records.get(relative)
    if not isinstance(record, dict) or record.get('signature') != signature:
        return None
    document = record.get('document')
    if not isinstance(document, dict) or document.get('status') != 'supported':
        return None
    raw_segments = document.get('segments')
    if not isinstance(raw_segments, list):
        return None
    method = str(document.get('extraction_method') or '').casefold()
    used_ocr = 'ocr' in method or 'vision' in method
    pages: dict[int, list[str]] = {}
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get('text')
        page = segment.get('page')
        if not isinstance(text, str) or not text.strip() or not isinstance(page, int) or page <= 0:
            continue
        pages.setdefault(page, []).append(text)
    if not pages:
        return None
    segments = [(f'page {number}', '\n'.join(parts), used_ocr) for number, parts in sorted(pages.items())]
    document_warnings = [warning for warning in document.get('warnings') or [] if isinstance(warning, str)]
    truncated = any(
        marker in warning.casefold()
        for warning in document_warnings
        for marker in _CACHE_INCOMPLETE_MARKERS
    )
    digest = document.get('content_hash')
    if not isinstance(digest, str) or not digest:
        digest = fingerprint(path)
    return digest, segments, truncated, len(segments), None, 0, []


def _cache_pdf_document(root: Path, path: Path, digest: str, segments: list[tuple[str, str, bool]]) -> None:
    """Persist extracted PDF text so later retrievals skip the expensive parse."""

    if path.suffix.lower() != '.pdf':
        return
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        signature = cache_signature(path)
        stored: list[dict[str, Any]] = []
        for index, (location, text, _ocr) in enumerate(segments):
            stored.append({
                'text': text,
                'page': int(location.rsplit(' ', 1)[-1]),
                'section': None,
                'start_line': None,
                'end_line': None,
                'index': index,
            })
    except (OSError, ValueError):
        return
    if not stored:
        return
    document = {
        'path': relative,
        'media_type': 'application/pdf',
        'segments': stored,
        'extraction_method': 'study-pypdf+ocr' if any(ocr for _location, _text, ocr in segments) else 'study-pypdf',
        'content_hash': digest,
        'status': 'supported',
        'warnings': [],
        'unsupported': [],
    }
    store = JsonStateStore(root / '.academia' / 'extracted_sources.json')

    def save(raw: Any) -> Any:
        state = raw if isinstance(raw, dict) else {'schema_version': 1, 'records': {}}
        records = state.get('records')
        if not isinstance(records, dict):
            records = {}
        previous = records.get(relative)
        # Keep a document the import worker already extracted for this exact version.
        if isinstance(previous, dict) and previous.get('signature') == signature and isinstance(previous.get('document'), dict):
            return state
        record = previous if isinstance(previous, dict) else {}
        record['signature'] = signature
        record['document'] = document
        records[relative] = record
        state['schema_version'] = 1
        state['records'] = records
        return state

    try:
        store.update({'schema_version': 1, 'records': {}}, save)
    except OSError:
        return


def _write_progress(
    root: Path,
    course: str,
    *,
    completed: int,
    total: int,
    source: str | None,
    status: str,
) -> None:
    """Record retrieval progress for the dashboard's local status poll."""

    record = {
        'status': status,
        'completed': completed,
        'total': total,
        'source': source,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    store = JsonStateStore(root / '.academia' / 'study_progress.json')

    def save(raw: Any) -> Any:
        state = raw if isinstance(raw, dict) else {'schema_version': 1, 'courses': {}}
        courses = state.get('courses')
        if not isinstance(courses, dict):
            courses = {}
        courses[course] = record
        state['schema_version'] = 1
        state['courses'] = courses
        return state

    try:
        store.update({'schema_version': 1, 'courses': {}}, save)
    except OSError:
        return


def read_progress(root: Path, semester: str, course: str) -> dict[str, Any]:
    """Return the latest local retrieval progress for one course."""

    directory = resolve_course_directory(root, semester, course)
    try:
        state = JsonStateStore(root / '.academia' / 'study_progress.json').read({'courses': {}})
    except (OSError, ValueError):
        state = {}
    courses = state.get('courses') if isinstance(state, dict) else None
    record = courses.get(directory.name) if isinstance(courses, dict) else None
    base = {'course_id': directory.name, 'semester': semester}
    if not isinstance(record, dict):
        return {**base, 'status': 'idle', 'completed': 0, 'total': 0, 'source': None, 'updated_at': None}
    return {
        **base,
        **{key: record.get(key) for key in ('status', 'completed', 'total', 'source', 'updated_at')},
    }


def _extract_pdf_source(path: str, root: str, ocr_pages: int, ocr_seconds: float) -> dict[str, Any]:
    """Process-pool entry point: extract one uncached PDF in a child process."""

    source = Path(path)
    workspace = Path(root)
    try:
        digest = fingerprint(source)
        segments, truncated, pages_scanned, page_count, ocr_attempted, ocr_notices = _segments(
            source,
            None,
            deep=True,
            workspace_root=workspace,
            digest=digest,
            ocr_budget=ocr_pages,
            ocr_seconds=ocr_seconds,
            # Workers must not race on the shared cache; the parent stores the text.
            write_ocr_cache=False,
        )
    except Exception as exc:
        return {'path': path, 'error': str(exc)}
    return {
        'path': path,
        'digest': digest,
        'segments': segments,
        'truncated': truncated,
        'pages_scanned': pages_scanned,
        'page_count': page_count,
        'ocr_attempted': ocr_attempted,
        'ocr_notices': ocr_notices,
    }


def _extraction_workers(total: int) -> int:
    override = os.environ.get('ACADEMIA_EXTRACT_WORKERS', '').strip()
    if override:
        try:
            return max(1, min(8, int(override)))
        except ValueError:
            pass
    return max(1, min(MAX_EXTRACTION_WORKERS, total, os.cpu_count() or 1))


def _segments(
    path: Path,
    pages: str | None,
    *,
    deep: bool = False,
    workspace_root: Path | None = None,
    digest: str | None = None,
    ocr_budget: int | None = None,
    ocr_seconds: float = MAX_STUDY_OCR_SECONDS,
    write_ocr_cache: bool = True,
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
                write_cache=write_ocr_cache,
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
    cache_records = _cache_state(root)
    names = {item['id']: item['name'] for item in selected}
    progress_total = len(selected)
    reported: set[str] = set()

    def report(item_id: str, name: str) -> None:
        if not deep or item_id in reported:
            return
        reported.add(item_id)
        _write_progress(root, directory.name, completed=len(reported), total=progress_total,
                        source=name, status='running')

    if deep:
        _write_progress(root, directory.name, completed=0, total=progress_total, source=None, status='running')

    prepared: dict[str, tuple[Any, ...]] = {}
    parallel: dict[str, dict[str, Any]] = {}
    if deep and pages is None:
        uncached: list[tuple[str, Path]] = []
        for item in selected:
            try:
                path = safe_path(root, Path(item['path']))
            except (OSError, ValueError):
                continue
            cached = _cached_pdf(root, path, cache_records)
            if cached is not None:
                prepared[item['id']] = cached
            elif path.suffix.lower() == '.pdf':
                uncached.append((item['id'], path))
        workers = _extraction_workers(len(uncached))
        if len(uncached) > 1 and workers > 1:
            pages_each = max(1, MAX_STUDY_OCR_PAGES // len(uncached))
            try:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(_extract_pdf_source, str(path), str(root), pages_each, MAX_STUDY_OCR_SECONDS): item_id
                        for item_id, path in uncached
                    }
                    for future in as_completed(futures):
                        item_id = futures[future]
                        parallel[item_id] = future.result()
                        report(item_id, names.get(item_id, 'source'))
            except Exception:
                # The pool is an optimization; the loop below retries the rest.
                parallel.clear()

    for item in selected:
        path = safe_path(root, Path(item['path']))
        try:
            # Page ranges keep the live bounded extraction; the cache stores whole documents.
            cached = prepared.get(item['id'])
            if cached is not None:
                digest, segments, truncated, pages_scanned, page_count, ocr_attempted, ocr_notices = cached
            elif item['id'] in parallel:
                result = parallel[item['id']]
                if 'error' in result:
                    raise ValueError(str(result['error']))
                digest = str(result['digest'])
                segments = list(result['segments'])
                truncated = bool(result['truncated'])
                pages_scanned = result['pages_scanned']
                page_count = result['page_count']
                ocr_attempted = int(result.get('ocr_attempted') or 0)
                ocr_notices = list(result.get('ocr_notices') or [])
                if not truncated and not ocr_notices:
                    _cache_pdf_document(root, path, digest, segments)
            else:
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
                # Cache only complete full-document extractions; a page range or
                # partial OCR would permanently hide the rest of the source.
                if deep and pages is None and not truncated and not ocr_notices:
                    _cache_pdf_document(root, path, digest, segments)
        except (OSError, ValueError) as exc:
            if pages and isinstance(exc, ValueError):
                raise
            report(item['id'], item['name'])
            warnings.append(f"{item['name']}: {exc}")
            continue
        except Exception:
            report(item['id'], item['name'])
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
        report(item['id'], item['name'])
    if deep:
        _write_progress(root, directory.name, completed=len(reported), total=progress_total,
                        source=None, status='completed')
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
