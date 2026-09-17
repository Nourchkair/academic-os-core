from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..domain import Evidence
from .models import CandidateFact, ExtractionResult, ExtractionStatus, SourceDocument, SourceSegment, extraction_timestamp


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_FULL_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\b", re.IGNORECASE)
_PARTIAL_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})\b", re.IGNORECASE)
_COURSE_CODE = re.compile(r"\b([A-Z]{2,6}\s*\d{3,4})\b")
_TIME_RANGE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:[AP]M)?)\s*(?:-|–|to)\s*(\d{1,2}:\d{2}\s*(?:[AP]M)?)\b", re.IGNORECASE)
_DAY = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _section_for_line(line: str, current: str | None) -> tuple[str | None, bool]:
    heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
    if heading:
        return heading.group(1).strip().rstrip(":"), True
    if line.strip().endswith(":") and len(line.strip()) <= 80 and not line.strip().startswith(("-", "*")):
        return line.strip().rstrip(":"), True
    if line.strip() and line.strip().isupper() and len(line.strip()) <= 80:
        return line.strip().title(), True
    return current, False


def _text_segments(text: str) -> tuple[SourceSegment, ...]:
    segments: list[SourceSegment] = []
    section: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        next_section, is_heading = _section_for_line(line, section)
        if is_heading:
            section = next_section
        segments.append(
            SourceSegment(
                text=line.strip(),
                section=section,
                start_line=line_number,
                end_line=line_number,
                index=line_number - 1,
            )
        )
    return tuple(segments)


def extract_source_document(path: Path) -> SourceDocument:
    path = Path(path).expanduser().resolve()
    if ".academia" in path.parts:
        raise ValueError("academic operational state cannot be extracted as source material")
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    digest = _hash_bytes(raw)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        return SourceDocument(str(path), "text/plain", _text_segments(raw.decode("utf-8", errors="replace")), "utf-8-text", digest)
    if suffix in {".md", ".markdown"}:
        return SourceDocument(str(path), "text/markdown", _text_segments(raw.decode("utf-8", errors="replace")), "utf-8-text", digest)
    if suffix == ".pdf":
        return _extract_pdf(path, raw, digest)
    return SourceDocument(
        str(path),
        "application/octet-stream",
        (),
        "unsupported",
        digest,
        status=ExtractionStatus.UNSUPPORTED_FORMAT,
        warnings=(f"Unsupported syllabus source format: {path.suffix or 'no extension'}.",),
        unsupported=("unsupported_format",),
    )


def _extract_pdf(path: Path, raw: bytes, digest: str) -> SourceDocument:
    try:
        from pypdf import PdfReader
    except ImportError:
        return SourceDocument(
            str(path), "application/pdf", (), "pypdf-unavailable", digest,
            status=ExtractionStatus.UNSUPPORTED_WITHOUT_OCR,
            warnings=("Text PDF extraction requires the optional local pypdf dependency; OCR is not enabled.",),
            unsupported=("unsupported_without_ocr",),
        )
    try:
        reader = PdfReader(str(path))
        segments = tuple(
            SourceSegment(text=(page.extract_text() or "").strip(), page=index + 1, index=index)
            for index, page in enumerate(reader.pages)
            if (page.extract_text() or "").strip()
        )
    except Exception as exc:
        return SourceDocument(
            str(path), "application/pdf", (), "pypdf", digest,
            status=ExtractionStatus.FAILED,
            warnings=(f"Local PDF text extraction failed: {exc}",),
            unsupported=("pdf_extraction_failed",),
        )
    if not segments:
        return SourceDocument(
            str(path), "application/pdf", (), "pypdf", digest,
            status=ExtractionStatus.UNSUPPORTED_WITHOUT_OCR,
            warnings=("No usable text was found. This PDF may be scanned or image-only; OCR is not enabled.",),
            unsupported=("unsupported_without_ocr",),
        )
    return SourceDocument(str(path), "application/pdf", segments, "pypdf-text", digest)


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value or "unknown"


def _stable_id(kind: str, course_id: str, title: str, source_hash: str) -> str:
    return f"{kind}:{_slug(course_id)}:{_slug(title)}:{source_hash[:12]}"


def _confidence(*, verified_current: bool, direct: bool = True, ambiguous: bool = False) -> str:
    if ambiguous or not direct:
        return "unverified"
    return "current-confirmed" if verified_current else "likely"


def _evidence(document: SourceDocument, segment: SourceSegment, confidence: str) -> Evidence:
    excerpt = segment.text[:280]
    return Evidence(
        source=Path(document.path).name,
        source_path=document.path,
        source_location=segment.source_location,
        provenance="ORIGINAL",
        confidence=confidence,
        authority="syllabus",
        last_verified_at=extraction_timestamp() if confidence == "current-confirmed" else None,
        source_hash=document.content_hash,
        reference={
            "segment": segment.index,
            "page": segment.page,
            "start_line": segment.start_line,
            "end_line": segment.end_line,
        },
        excerpt=excerpt,
    )


def _clean_bullet(text: str) -> str:
    return re.sub(r"^\s*[-*•]\s*", "", text).strip()


def _is_assessment(segment: SourceSegment) -> bool:
    section = (segment.section or "").casefold()
    return any(term in section for term in ("assessment", "assignment", "exam", "grading"))


def _assignment_title(text: str) -> str:
    clean = _clean_bullet(text)
    clean = re.split(r"\s+[—–|]\s+(?=(?:\d+(?:\.\d+)?\s*%|due\b|deadline\b))", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    clean = re.split(r"\s+(?:due|deadline)\b", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    return clean.strip(" :-—–|")


def _date_from_segment(text: str) -> tuple[str | None, bool]:
    full = _FULL_DATE.search(text)
    if full:
        parsed = datetime.strptime(f"{full.group(1)} {full.group(2)} {full.group(3)}", "%B %d %Y")
        return parsed.date().isoformat(), False
    return (None, bool(_PARTIAL_DATE.search(text)))


def _assessment_candidates(document: SourceDocument, course_id: str, verified_current: bool) -> tuple[list[CandidateFact], list[str]]:
    candidates: list[CandidateFact] = []
    warnings: list[str] = []
    for segment in document.segments:
        lower = segment.text.casefold()
        weight_match = re.search(r"\b(\d+(?:\.\d+)?)\s*%", segment.text)
        has_due = bool(re.search(r"\b(?:due|deadline)\b", lower))
        if not (weight_match or has_due or _is_assessment(segment)):
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+", segment.text) or segment.text.strip().rstrip(":").casefold() == (segment.section or "").casefold():
            continue
        title = _assignment_title(segment.text)
        if not title or title.casefold() in {"assessments", "assignments", "exams", "grading"}:
            continue
        date_value, partial = _date_from_segment(segment.text)
        confidence = _confidence(verified_current=verified_current, ambiguous=partial or (has_due and date_value is None and "near" in lower))
        if partial or (has_due and date_value is None):
            warnings.append(f"Ambiguous or incomplete deadline evidence for {title}; precise date was not stored.")
        assignment = {
            "id": _stable_id("assignment", course_id, title, document.content_hash),
            "course_id": course_id,
            "title": title,
            "deadline": date_value,
            "weight": f"{weight_match.group(1)}%" if weight_match else None,
            "instructions_source": None,
            "rubric_source": None,
            "submission_method": None,
            "status": None,
        }
        candidates.append(CandidateFact("assignment", "assignment", assignment, _evidence(document, segment, confidence), confidence, "Direct assessment line in syllabus."))
        if date_value:
            deadline = {
                "id": _stable_id("deadline", course_id, title, document.content_hash),
                "course_id": course_id,
                "title": title,
                "date": date_value,
                "time": None,
                "type": "assignment",
            }
            candidates.append(CandidateFact("deadline", "deadline", deadline, _evidence(document, segment, confidence), confidence, "Explicit dated deadline in syllabus."))
    return candidates, warnings


def _reading_candidates(document: SourceDocument, course_id: str, verified_current: bool) -> list[CandidateFact]:
    candidates: list[CandidateFact] = []
    for segment in document.segments:
        section = (segment.section or "").casefold()
        raw = _clean_bullet(segment.text)
        if "reading" not in section or raw.casefold() == section:
            continue
        if raw.startswith("#") or not raw:
            continue
        isbn_match = re.search(r"\bISBN(?:-\d+)?\s*([0-9Xx-]+)", raw, re.IGNORECASE)
        doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", raw, re.IGNORECASE)
        chapter_match = re.search(r"\bChapter\s+([\w-]+)", raw, re.IGNORECASE)
        pages_match = re.search(r"\bpp?\.?\s*([\d–-]+)", raw, re.IGNORECASE)
        edition_match = re.search(r"\b(\d+(?:st|nd|rd|th)\s+ed(?:ition)?)\b", raw, re.IGNORECASE)
        author: str | None = None
        title = raw
        first_period = raw.find(".")
        if first_period > 0 and "," in raw[:first_period]:
            author = raw[:first_period].strip()
            title = raw[first_period + 1:].strip()
        title = re.sub(r"\s*\([^)]*\d{4}[^)]*\)", "", title).strip(" .")
        for match in (isbn_match, doi_match, chapter_match, pages_match, edition_match):
            if match:
                title = title.replace(match.group(0), "")
        title = re.sub(r"\s*,\s*$", "", re.sub(r"\s{2,}", " ", title)).strip(" ,.")
        confidence = _confidence(verified_current=verified_current)
        reading = {
            "id": _stable_id("reading", course_id, title, document.content_hash),
            "course_id": course_id,
            "title": title or raw,
            "week_or_topic": segment.section,
            "author": author,
            "edition": edition_match.group(1) if edition_match else None,
            "chapter": chapter_match.group(1) if chapter_match else None,
            "pages": pages_match.group(1) if pages_match else None,
            "doi": doi_match.group(0) if doi_match else None,
            "isbn": isbn_match.group(1) if isbn_match else None,
            "required": True,
            "verification_result": "NOT RETRIEVED",
        }
        candidates.append(CandidateFact("required_reading", "reading", reading, _evidence(document, segment, confidence), confidence, "Direct reading entry under a required-reading section."))
    return candidates


def _meeting_candidates(document: SourceDocument, course_id: str, verified_current: bool) -> list[CandidateFact]:
    candidates: list[CandidateFact] = []
    for segment in document.segments:
        day = _DAY.search(segment.text)
        times = _TIME_RANGE.search(segment.text)
        section = (segment.section or "").casefold()
        if not day or not times or not ("meeting" in section or "schedule" in section or day):
            continue
        parts = [part.strip() for part in segment.text.split(",")]
        location = parts[1] if len(parts) > 1 else None
        title = day.group(1).title()
        confidence = _confidence(verified_current=verified_current)
        meeting = {
            "id": _stable_id("meeting", course_id, f"{title}-{times.group(1)}", document.content_hash),
            "course_id": course_id,
            "title": title,
            "starts_at": times.group(1),
            "ends_at": times.group(2),
            "location": location,
            "meeting_type": "class",
        }
        candidates.append(CandidateFact("course_meeting", "course_meeting", meeting, _evidence(document, segment, confidence), confidence, "Direct weekly meeting entry in syllabus."))
    return candidates


def _course_identity(document: SourceDocument, course_id: str, verified_current: bool) -> CandidateFact | None:
    for segment in document.segments:
        match = _COURSE_CODE.search(segment.text)
        if not match:
            continue
        code = re.sub(r"\s+", " ", match.group(1).strip())
        tail = segment.text[match.end():].strip(" :-—–")
        title = tail or segment.text[:match.start()].strip(" #-:") or Path(document.path).stem
        confidence = _confidence(verified_current=verified_current, direct=True)
        entity = {
            "id": f"source:{document.content_hash[:16]}",
            "course_id": course_id,
            "title": title,
            "kind": "syllabus",
            "metadata": {"detected_course_code": code, "detected_course_title": title},
        }
        return CandidateFact("course_identity", "academic_source", entity, _evidence(document, segment, confidence), confidence, "Direct course identity line in syllabus.")
    return None


def _course_code(value: str) -> str | None:
    match = _COURSE_CODE.search(value)
    return re.sub(r"\s+", " ", match.group(1).strip()).casefold() if match else None


def _downgrade_identity_uncertainty(candidates: Iterable[CandidateFact], confidence: str) -> tuple[CandidateFact, ...]:
    return tuple(
        replace(
            candidate,
            confidence=confidence,
            evidence=replace(candidate.evidence, confidence=confidence, last_verified_at=None),
            reason=f"{candidate.reason} Course identity was not sufficiently established.",
        )
        for candidate in candidates
    )


def extract_syllabus(path: Path, *, course_id: str, verified_current: bool = False) -> ExtractionResult:
    course_id = course_id.strip()
    if not course_id:
        raise ValueError("syllabus extraction requires an explicit course id; Academia will not guess one")
    document = extract_source_document(path)
    warnings = list(document.warnings)
    if document.status is not ExtractionStatus.SUPPORTED:
        return ExtractionResult(document, "syllabus", extraction_timestamp(), warnings=tuple(warnings), unsupported=document.unsupported)
    candidates: list[CandidateFact] = []
    identity = _course_identity(document, course_id, verified_current)
    identity_status = "unknown"
    if identity:
        detected_code = str(identity.entity.get("metadata", {}).get("detected_course_code", ""))
        if _course_code(detected_code) == _course_code(course_id):
            identity_status = "matched"
            candidates.append(identity)
        else:
            identity_status = "mismatch"
            mismatch = replace(identity, confidence="unverified", evidence=replace(identity.evidence, confidence="unverified", last_verified_at=None), reason="The syllabus course identity does not match the supplied course context.")
            candidates.append(mismatch)
            warnings.append(f"Syllabus course identity {detected_code} does not match supplied course {course_id}; no facts will be projected automatically.")
    else:
        warnings.append("No direct course identity line was found; the supplied course id remains user-provided context.")
    assessment_items, assessment_warnings = _assessment_candidates(document, course_id, verified_current)
    candidates.extend(assessment_items)
    warnings.extend(assessment_warnings)
    candidates.extend(_reading_candidates(document, course_id, verified_current))
    candidates.extend(_meeting_candidates(document, course_id, verified_current))
    if identity_status == "mismatch":
        candidates = list(_downgrade_identity_uncertainty(candidates, "unverified"))
    elif identity_status == "unknown" and verified_current:
        candidates = list(_downgrade_identity_uncertainty(candidates, "likely"))
    return ExtractionResult(document, "syllabus", extraction_timestamp(), tuple(candidates), tuple(warnings), document.unsupported, identity_status)
