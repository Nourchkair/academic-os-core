from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from ..domain import Evidence
from .models import CandidateFact, ExtractionResult, ExtractionStatus, SourceDocument, SourceSegment, extraction_timestamp


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_FULL_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\b", re.IGNORECASE)
_PARTIAL_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})\b", re.IGNORECASE)
_COURSE_CODE = re.compile(r"\b([A-Z]{2,6}\s*\d{3,4})(?:[A-Z]\d{0,2})?\b")
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
    if suffix in {".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}:
        return _extract_image(path, raw, digest)
    if suffix == ".docx":
        return _extract_docx(path, digest)
    if suffix == ".pptx":
        return _extract_pptx(path, digest)
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
        page_texts = [(index + 1, (page.extract_text() or "").strip()) for index, page in enumerate(reader.pages)]
        segments = tuple(SourceSegment(text=text, page=number, index=number - 1) for number, text in page_texts if text)
    except Exception as exc:
        return SourceDocument(
            str(path), "application/pdf", (), "pypdf", digest,
            status=ExtractionStatus.FAILED,
            warnings=(f"Local PDF text extraction failed: {exc}",),
            unsupported=("pdf_extraction_failed",),
        )
    scanned_pages = [number for number, text in page_texts if not text]
    if not scanned_pages:
        return SourceDocument(str(path), "application/pdf", segments, "pypdf-text", digest)

    # OCR only pages without a text layer. This keeps hybrid PDFs complete
    # without needlessly rasterizing pages that pypdf already extracted.
    from ..pdf_ocr import ocr_pdf_pages

    ocr_pages, _, skipped_pages, notices = ocr_pdf_pages(
        path,
        scanned_pages,
        digest=digest,
        max_pages=250,
        max_seconds=600,
    )
    ocr_segments = tuple(
        SourceSegment(text=text, page=number, index=number - 1)
        for number, text in sorted(ocr_pages.items())
        if text.strip()
    )
    if ocr_segments:
        combined = tuple(sorted((*segments, *ocr_segments), key=lambda item: (item.page or 0, item.index)))
        warnings = ("OCR text may contain recognition errors; verify against the preserved source.",)
        if skipped_pages:
            warnings += (f"OCR did not extract {len(skipped_pages)} scanned page(s); coverage is incomplete.",)
        warnings += tuple(notices)
        method = "pypdf-text+tesseract-ocr" if segments else "tesseract-pdf-ocr"
        return SourceDocument(str(path), "application/pdf", combined, method, digest, warnings=tuple(dict.fromkeys(warnings)))
    if segments:
        warning = tuple(notices) or ("Some PDF pages have no extractable text and local OCR found no readable text.",)
        return SourceDocument(str(path), "application/pdf", segments, "pypdf-text", digest, warnings=warning)

    # Keep Vision as a fallback for systems without Poppler/Tesseract, and
    # retain both diagnostics if neither OCR path can read the document.
    vision = _extract_vision(path, "application/pdf", digest, is_pdf=True)
    if vision.status is ExtractionStatus.SUPPORTED and vision.segments:
        return vision
    warnings = tuple(notices) + vision.warnings
    return replace(vision, warnings=tuple(dict.fromkeys(warnings)))


def _extract_image(path: Path, raw: bytes, digest: str) -> SourceDocument:
    media_type = {
        ".bmp": "image/bmp", ".gif": "image/gif", ".heic": "image/heic", ".heif": "image/heif",
        ".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".tif": "image/tiff",
        ".tiff": "image/tiff", ".webp": "image/webp",
    }[path.suffix.lower()]
    vision = _extract_vision(path, media_type, digest, is_pdf=False)
    if vision.status is ExtractionStatus.SUPPORTED and vision.segments:
        return vision

    # Vision is preferred on macOS, but image imports should still work when
    # its Swift bridge fails or is unavailable. Tesseract reads the original
    # image directly and writes no sidecar files.
    recognizer = shutil.which("tesseract")
    if recognizer:
        try:
            result = subprocess.run(
                [recognizer, str(path), "stdout", "-l", "eng", "--psm", "3"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                vision_issue = "; ".join(vision.warnings) if vision.status is ExtractionStatus.FAILED else "Vision returned no readable text"
                return SourceDocument(
                    str(path),
                    media_type,
                    (SourceSegment(text=result.stdout.strip()[:1_500_000], page=1, index=0),),
                    "tesseract-ocr",
                    digest,
                    warnings=(
                        f"Tesseract OCR was used because {vision_issue or 'Vision OCR was unavailable'}. "
                        "OCR text may contain recognition errors; verify against the preserved source.",
                    ),
                )
            tesseract_issue = result.stderr.strip()[-500:] or f"Tesseract exited with status {result.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            tesseract_issue = str(exc)
    else:
        tesseract_issue = "Tesseract is not installed"

    vision_issue = "; ".join(vision.warnings) or "Vision OCR found no readable text"
    return replace(
        vision,
        extraction_method="image-ocr-failed",
        status=ExtractionStatus.FAILED,
        warnings=(f"Image OCR failed. Vision: {vision_issue}. Tesseract: {tesseract_issue}.",),
        unsupported=("ocr_failed",),
    )


_VISION_OCR_SOURCE = r'''import AppKit
import Foundation
import ImageIO
import PDFKit
import Vision

let source = URL(fileURLWithPath: CommandLine.arguments[1])
let isPDF = CommandLine.arguments[2] == "pdf"
let maxPages = 250
let maxCharacters = 1500000
var pages: [[String: Any]] = []
var characterCount = 0
var wasTruncated = false

func recognize(_ image: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["en-US"]
    do { try VNImageRequestHandler(cgImage: image).perform([request]) }
    catch { return "" }
    return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func append(_ page: Int, _ text: String) {
    guard !text.isEmpty else { return }
    let remaining = maxCharacters - characterCount
    guard remaining > 0 else { wasTruncated = true; return }
    let bounded = String(text.prefix(remaining))
    pages.append(["page": page, "text": bounded])
    characterCount += bounded.count
    if bounded.count < text.count { wasTruncated = true }
}

if isPDF {
    if let document = PDFDocument(url: source) {
        let count = min(document.pageCount, maxPages)
        for index in 0..<count {
            guard let page = document.page(at: index) else { continue }
            let image = page.thumbnail(of: NSSize(width: 2200, height: 2800), for: .mediaBox)
            if let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) {
                append(index + 1, recognize(cgImage))
            }
        }
        if document.pageCount > maxPages { wasTruncated = true }
    }
} else if let sourceRef = CGImageSourceCreateWithURL(source as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(sourceRef, 0, nil) {
    append(1, recognize(image))
}

let output: [String: Any] = ["pages": pages, "truncated": wasTruncated]
let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
'''


def _extract_vision(path: Path, media_type: str, digest: str, *, is_pdf: bool) -> SourceDocument:
    unsupported = SourceDocument(
        str(path), media_type, (), "ocr-unavailable", digest,
        status=ExtractionStatus.UNSUPPORTED_WITHOUT_OCR,
        warnings=("Local OCR requires macOS Vision and the Swift runtime; the source was preserved without extracted text.",),
        unsupported=("unsupported_without_ocr",),
    )
    if sys.platform != "darwin" or shutil.which("swift") is None:
        return unsupported

    try:
        with tempfile.TemporaryDirectory(prefix="academia-ocr-") as temporary:
            script = Path(temporary) / "vision_ocr.swift"
            script.write_text(_VISION_OCR_SOURCE, encoding="utf-8")
            result = subprocess.run(
                ["swift", str(script), str(path), "pdf" if is_pdf else "image"],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        if result.returncode != 0:
            message = result.stderr.strip()[-1000:]
            return replace(
                unsupported,
                extraction_method="macos-vision-failed",
                status=ExtractionStatus.FAILED,
                warnings=(f"Local macOS Vision OCR could not process this source: {message or 'unknown error'}",),
                unsupported=("ocr_failed",),
            )
        payload = json.loads(result.stdout)
        pages = payload.get("pages", [])
        segments = tuple(
            SourceSegment(text=str(item.get("text", "")).strip(), page=int(item.get("page", index + 1)), index=index)
            for index, item in enumerate(pages)
            if str(item.get("text", "")).strip()
        )
        if not segments:
            return replace(
                unsupported,
                extraction_method="macos-vision",
                warnings=("Local OCR found no readable text in this source.",),
            )
        warnings = ("OCR text may contain recognition errors; verify against the preserved source.",)
        if payload.get("truncated"):
            warnings += ("OCR reached the local page or text limit; later content may be omitted.",)
        return SourceDocument(str(path), media_type, segments, "macos-vision", digest, warnings=warnings)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError) as exc:
        return replace(
            unsupported,
            extraction_method="macos-vision-failed",
            status=ExtractionStatus.FAILED,
            warnings=(f"Local macOS Vision OCR could not process this source: {exc}",),
            unsupported=("ocr_failed",),
        )


def _extract_docx(path: Path, digest: str) -> SourceDocument:
    """Preserve paragraphs and table rows without installing an Office runtime."""
    try:
        with ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        body = root.find("w:body", ns)
        lines: list[str] = []
        for element in body if body is not None else ():
            rows = element.findall("w:tr", ns) if element.tag.endswith("}tbl") else [element]
            for row in rows:
                cells = row.findall("w:tc", ns) if row.tag.endswith("}tr") else [row]
                lines.append(" | ".join("".join(t.text or "" for t in cell.findall(".//w:t", ns)).strip() for cell in cells))
        return SourceDocument(str(path), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _text_segments("\n".join(lines)), "docx-xml", digest)
    except (OSError, ValueError, KeyError, BadZipFile, ElementTree.ParseError) as exc:
        return SourceDocument(str(path), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", (), "docx-xml", digest, status=ExtractionStatus.FAILED, warnings=(f"Local DOCX extraction failed: {exc}",), unsupported=("docx_extraction_failed",))


def _extract_pptx(path: Path, digest: str) -> SourceDocument:
    """Extract visible text from slide XML without an Office runtime."""
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    segments: list[SourceSegment] = []
    warnings: list[str] = []
    character_count = 0
    max_slides = 500
    max_characters = 1_500_000
    try:
        with ZipFile(path) as archive:
            slide_files = []
            for info in archive.infolist():
                match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename)
                if match:
                    slide_files.append((int(match.group(1)), info))
            slide_files.sort(key=lambda item: item[0])
            if len(slide_files) > max_slides:
                slide_files = slide_files[:max_slides]
                warnings.append(f"Only the first {max_slides} slides were extracted.")

            for slide_number, info in slide_files:
                root = ElementTree.fromstring(archive.read(info))
                for paragraph in root.findall(".//a:p", namespace):
                    text = "".join(node.text or "" for node in paragraph.findall(".//a:t", namespace)).strip()
                    if not text:
                        continue
                    remaining = max_characters - character_count
                    if remaining <= 0:
                        warnings.append("Slide text extraction reached the 1,500,000 character limit; later text may be omitted.")
                        break
                    bounded = text[:remaining]
                    segments.append(SourceSegment(text=bounded, section=f"Slide {slide_number}", index=len(segments)))
                    character_count += len(bounded)
                    if len(bounded) < len(text):
                        warnings.append("Slide text extraction reached the 1,500,000 character limit; later text may be omitted.")
                        break
                if character_count >= max_characters:
                    break

            if any(name.startswith("ppt/media/") for name in archive.namelist()):
                warnings.append("Text extraction does not OCR embedded images or include speaker notes; verify visual slide content in the preserved presentation.")
    except (OSError, ValueError, KeyError, BadZipFile, ElementTree.ParseError) as exc:
        return SourceDocument(str(path), media_type, (), "pptx-openxml", digest, status=ExtractionStatus.FAILED, warnings=(f"Local PPTX slide text extraction failed: {exc}",), unsupported=("pptx_extraction_failed",))

    if not segments:
        return SourceDocument(
            str(path), media_type, (), "pptx-openxml", digest,
            status=ExtractionStatus.UNSUPPORTED_WITHOUT_OCR,
            warnings=tuple(warnings) + ("No machine-readable slide text was found; image-only slides were preserved without OCR.",),
            unsupported=("pptx_without_text",),
        )
    return SourceDocument(str(path), media_type, tuple(segments), "pptx-openxml", digest, warnings=tuple(warnings))


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
    if document.media_type in {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        return _formatted_assessments(document, course_id, verified_current)
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


def _formatted_assessments(document: SourceDocument, course_id: str, verified_current: bool) -> tuple[list[CandidateFact], list[str]]:
    """Read explicit assessment rows/sentences; never interpret an entire PDF page as a task.

    A yearless date is accepted only when the document names one academic term
    year. Unknown signup dates and final-exam dates remain unknown.
    """
    years = set(re.findall(r"\b(?:Fall|Winter|Spring|Summer)\s*(?:term\s*)?(20\d{2})\b", document.full_text, re.IGNORECASE))
    year = next(iter(years)) if len(years) == 1 else None
    date_pattern = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d{{2}}))?\b", re.IGNORECASE)
    title_pattern = re.compile(r"^(?:In[- ]class\s+)?(?P<title>(?:First|Second)\s+Essay|Essay\s+(?:One|Two|\d+)|Quiz\s*\d+|Mid[- ]?term(?:\s+Exam)?(?:\s*#?\s*\d+)?|Final\s+Exam|Prepared Question Prompts|On[- ]?Line Commenting|Participation)\b", re.IGNORECASE)
    found: dict[str, dict] = {}
    warnings: list[str] = []
    calendar_date: str | None = None
    for original in document.segments:
        # Separate wrapped prose assessments (e.g. "Essay One ... Essay Two ...")
        # while retaining the original PDF page or DOCX paragraph reference.
        block = re.sub(r"Prepared Question\s*\n\s*Prompts", "Prepared Question Prompts", original.text, flags=re.IGNORECASE)
        block = re.sub(r"On-Line\s*\n\s*Commenting", "On-Line Commenting", block, flags=re.IGNORECASE)
        lines = re.split(r"\n|(?=\bEssay (?:One|Two)\s*\(due)", block)
        for line in lines:
            text = re.sub(r"^\d+\.\s+", "", " ".join(line.split()).lstrip("• "))
            date_match = date_pattern.search(text)
            date_value = None
            if date_match and (date_match.group(3) or year):
                try:
                    date_value = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3) or year}", "%B %d %Y").date().isoformat()
                except ValueError:
                    warnings.append(f"Invalid date was not stored: {text}")
            if re.match(rf"^({_MONTHS})\s+\d{{1,2}}", text, re.IGNORECASE) and re.search(r"\bLECTURE\s+\d+\b", text, re.IGNORECASE):
                calendar_date = date_value
            title_match = title_pattern.match(text)
            if not title_match:
                continue
            weight = re.search(r"\b(\d+(?:\.\d+)?)\s*%", text)
            has_due = bool(re.search(r"\b(?:due|expected date|deadline|at)\b", text, re.IGNORECASE))
            if not (weight or date_match or has_due):
                continue
            title = title_match.group("title")
            key = re.sub(r"[\s#-]+", " ", title.casefold()).strip()
            aliases = {"essay one": "First Essay", "first essay": "First Essay", "essay two": "Second Essay", "second essay": "Second Essay", "mid term": "Midterm Exam", "mid term exam": "Midterm Exam", "midterm": "Midterm Exam", "midterm exam": "Midterm Exam", "on line commenting": "Online Commenting", "online commenting": "Online Commenting"}
            title = aliases.get(key, title.title())
            key = title.casefold()
            if date_value is None and re.match(r"^Quiz\s*\d+\s+AT\b", text, re.IGNORECASE):
                date_value = calendar_date
            time_match = re.search(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?", text, re.IGNORECASE)
            time_value = None
            if time_match and 1 <= int(time_match.group(1)) <= 12 and int(time_match.group(2)) < 60:
                hour = int(time_match.group(1)) % 12 + (12 if time_match.group(3).lower() == "p" else 0)
                time_value = f"{hour:02}:{time_match.group(2)}"
            segment = replace(original, text=text)
            confidence = _confidence(verified_current=verified_current, ambiguous=bool(date_match and not date_value))
            if date_match and not date_value:
                warnings.append(f"No unambiguous term year for {title}; precise date was not stored.")
            if key not in found:
                found[key] = {"title": title, "date": date_value, "time": time_value, "weight": f"{weight.group(1)}%" if weight else None, "evidence": _evidence(document, segment, confidence), "confidence": confidence}
            else:
                item = found[key]
                if date_value and item["date"] and item["date"] != date_value:
                    warnings.append(f"Conflicting dates within syllabus for {title}; retained first date for review.")
                    item["confidence"] = "unverified"
                    item["evidence"] = replace(item["evidence"], confidence="unverified", last_verified_at=None)
                elif date_value and (not item["date"] or time_value):
                    item.update(date=date_value, time=time_value or item["time"], evidence=_evidence(document, segment, confidence))
                if weight and not item["weight"]:
                    item["weight"] = f"{weight.group(1)}%"
        # A forum-wide cutoff is distinct from a student's unknown PQP signup.
        # Read it only within the explicitly named commenting section.
        commenting = re.search(r"Online Commenting\s*\(\d+%\)(.*?)(?=Important:|Assessment Policies|$)", original.text, re.IGNORECASE | re.DOTALL)
        if commenting and "online commenting" in found:
            cutoff = re.search(r"overall\s+deadline.{0,180}?\b(" + _MONTHS + r")\s+(\d{1,2})(?:st|nd|rd|th)?", commenting.group(1), re.IGNORECASE | re.DOTALL)
            if cutoff and year:
                try:
                    date_value = datetime.strptime(f"{cutoff.group(1)} {cutoff.group(2)} {year}", "%B %d %Y").date().isoformat()
                except ValueError:
                    continue
                confidence = _confidence(verified_current=verified_current)
                found["online commenting"].update(date=date_value, confidence=confidence, evidence=_evidence(document, replace(original, text=cutoff.group(0)), confidence))
    candidates: list[CandidateFact] = []
    for item in found.values():
        title = item["title"]
        assignment = {"id": _stable_id("assignment", course_id, title, document.content_hash), "course_id": course_id, "title": title, "deadline": item["date"], "weight": item["weight"], "instructions_source": None, "rubric_source": None, "submission_method": None, "status": None}
        candidates.append(CandidateFact("assignment", "assignment", assignment, item["evidence"], item["confidence"], "Explicit assessment row or dated assessment sentence in syllabus."))
        if item["date"]:
            deadline = {"id": _stable_id("deadline", course_id, title, document.content_hash), "course_id": course_id, "title": title, "date": item["date"], "time": item["time"], "type": "exam" if re.search("quiz|exam|midterm", title, re.IGNORECASE) else "assignment"}
            candidates.append(CandidateFact("deadline", "deadline", deadline, item["evidence"], item["confidence"], "Explicit assessment date using the document's named academic term year."))
    return candidates, warnings


def _reading_candidates(document: SourceDocument, course_id: str, verified_current: bool) -> list[CandidateFact]:
    # Word's unstyled headings and table columns do not provide reliable section
    # boundaries. Keep those readings in Library rather than project prose as facts.
    if document.extraction_method == "docx-xml":
        return []
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


def _downgrade_ocr_uncertainty(candidates: Iterable[CandidateFact]) -> tuple[CandidateFact, ...]:
    reason = "OCR may misrecognize source text; verify against the original document."
    return tuple(
        replace(
            candidate,
            confidence="unverified",
            evidence=replace(candidate.evidence, confidence="unverified", last_verified_at=None),
            reason=f"{candidate.reason} {reason}",
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
    if document.extraction_method.startswith("macos-vision"):
        candidates = list(_downgrade_ocr_uncertainty(candidates))
        warnings.append("Facts extracted from OCR remain unverified until checked against the original source.")
    if identity_status == "mismatch":
        candidates = list(_downgrade_identity_uncertainty(candidates, "unverified"))
    elif identity_status == "unknown" and verified_current:
        candidates = list(_downgrade_identity_uncertainty(candidates, "likely"))
    return ExtractionResult(document, "syllabus", extraction_timestamp(), tuple(candidates), tuple(warnings), document.unsupported, identity_status)
