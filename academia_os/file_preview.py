from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from .library import list_material
from .processing import cache_signature
from .state import JsonStateStore

MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_CHARS = 120_000
TEXT_EXTENSIONS = frozenset({".csv", ".json", ".md", ".markdown", ".txt", ".text", ".yaml", ".yml"})
IMAGE_MIME_TYPES = {".gif": "image/gif", ".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
IMAGE_EXTENSIONS = frozenset(IMAGE_MIME_TYPES)
MAX_IMAGE_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_OFFICE_XML_BYTES = 8 * 1024 * 1024
MAX_OFFICE_TOTAL_XML_BYTES = 16 * 1024 * 1024
PREVIEW_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {".docx", ".pdf", ".pptx"}


class FilePreviewError(ValueError):
    """A requested Library file cannot be safely previewed."""


def resolve_library_file(path: Path, *, workspace_root: Path, semester: str) -> tuple[Path, dict[str, Any]]:
    """Resolve *path* only when it is an indexed file in the active semester."""

    requested = Path(path).expanduser()
    if not requested.is_absolute():
        raise FilePreviewError("Library previews require an absolute local file path")
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise FilePreviewError("The selected Library file is no longer available") from exc
    if not resolved.is_file() or requested.is_symlink():
        raise FilePreviewError("The selected Library item is not a regular file")

    root = Path(workspace_root).expanduser().resolve()
    for item in list_material(root, semester):
        try:
            item_path = Path(str(item["path"])).resolve(strict=True)
        except OSError:
            continue
        if item_path == resolved:
            return resolved, item
    raise FilePreviewError("The selected file is not part of the active semester Library")


def preview_file(path: Path, *, workspace_root: Path, semester: str, include_image_data: bool = False) -> dict[str, Any]:
    """Return a read-only, bounded preview for one indexed Library file."""

    resolved, item = resolve_library_file(path, workspace_root=workspace_root, semester=semester)
    extension = resolved.suffix.casefold()
    if extension not in PREVIEW_EXTENSIONS:
        raise FilePreviewError(f"Preview is not available for {extension or 'this file type'}")

    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise FilePreviewError("The selected Library file could not be read") from exc

    if extension in TEXT_EXTENSIONS:
        content, truncated = _read_text(resolved)
        kind = "text"
    elif extension == ".pdf":
        content, truncated = _read_cached_pdf(resolved, Path(workspace_root).expanduser().resolve()) or _read_pdf(resolved)
        kind = "pdf"
    elif extension in IMAGE_EXTENSIONS:
        if size > MAX_IMAGE_PREVIEW_BYTES:
            raise FilePreviewError("Image preview is limited to 8 MB. Open the original file to view this image.")
        content, truncated = "", False
        kind = "image"
    else:
        content, truncated = read_office_text(resolved, extension)
        kind = "text"

    result = {
        "id": item["id"],
        "name": resolved.name,
        "extension": extension,
        "kind": kind,
        "size": size,
        "content": content,
        "truncated": truncated,
    }
    if kind == "image" and include_image_data:
        try:
            encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
        except OSError as exc:
            raise FilePreviewError("The selected image could not be read") from exc
        result["image_data_url"] = f"data:{IMAGE_MIME_TYPES[extension]};base64,{encoded}"
    return result


def _read_text(path: Path) -> tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FilePreviewError("The selected text file could not be read") from exc
    truncated = len(raw) > MAX_PREVIEW_BYTES
    text = raw[:MAX_PREVIEW_BYTES].decode("utf-8", errors="replace")
    return _bound_text(text, truncated)


def _read_pdf(path: Path) -> tuple[str, bool]:
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        total_chars = 0
        truncated = False
        for page in reader.pages:
            text = page.extract_text() or ""
            remaining = MAX_PREVIEW_CHARS - total_chars
            if remaining <= 0:
                truncated = True
                break
            pages.append(text[:remaining])
            total_chars += len(text)
            if len(text) > remaining:
                truncated = True
                break
        return "\n\n".join(pages).strip(), truncated
    except Exception as exc:  # pypdf uses several exception types for malformed/encrypted PDFs.
        del exc
        return "", False


def _read_cached_pdf(path: Path, workspace_root: Path) -> tuple[str, bool] | None:
    try:
        relative = path.resolve(strict=True).relative_to(workspace_root.resolve()).as_posix()
        state = JsonStateStore(workspace_root / ".academia" / "extracted_sources.json").read({"records": {}})
        records = state.get("records", {}) if isinstance(state, dict) else {}
        record = records.get(relative) if isinstance(records, dict) else None
        if not isinstance(record, dict) or record.get("signature") != cache_signature(path):
            return None
        document = record.get("document")
        if not isinstance(document, dict) or document.get("status") != "supported":
            return None
        segments = document.get("segments")
        if not isinstance(segments, list):
            return None
        pages = [str(segment.get("text", "")) for segment in segments if isinstance(segment, dict)]
        return _bound_text("\n\n".join(pages).strip(), False)
    except (OSError, ValueError, TypeError):
        return None


def read_office_text(path: Path, extension: str, *, max_chars: int = MAX_PREVIEW_CHARS) -> tuple[str, bool]:
    """Extract visible text from a DOCX or PPTX file within explicit bounds."""
    prefix = "word/" if extension == ".docx" else "ppt/slides/"
    try:
        with ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".xml"))
            if extension == ".docx":
                names = [name for name in names if name == "word/document.xml" or "/header" in name or "/footer" in name]
            else:
                names = [name for name in names if "/slide" in name]
            passages: list[str] = []
            total_xml_bytes = 0
            truncated = False
            for name in names:
                remaining = MAX_OFFICE_TOTAL_XML_BYTES - total_xml_bytes
                if remaining <= 0:
                    truncated = True
                    break
                with archive.open(name) as source:
                    raw = source.read(min(MAX_OFFICE_XML_BYTES, remaining) + 1)
                if len(raw) > min(MAX_OFFICE_XML_BYTES, remaining):
                    truncated = True
                    continue
                total_xml_bytes += len(raw)
                passages.append(_xml_visible_text(raw))
            text = "\n\n".join(passages)
    except (OSError, BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise FilePreviewError(f"This {extension[1:].upper()} file could not be read as an office document") from exc
    if len(text) > max_chars:
        return text[:max_chars], True
    return text.strip(), truncated


def _xml_visible_text(raw: bytes) -> str:
    root = ElementTree.fromstring(raw)
    paragraphs: list[str] = []
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1]
        if local not in {"p", "sp"}:
            continue
        line = "".join(
            (child.text or "")
            for child in element.iter()
            if child.tag.rsplit("}", 1)[-1] in {"t", "text"}
        ).strip()
        if line:
            paragraphs.append(line)
    if paragraphs:
        return "\n".join(paragraphs)
    return "\n".join(
        element.text.strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] in {"t", "text"} and element.text and element.text.strip()
    )


def _bound_text(text: str, truncated: bool) -> tuple[str, bool]:
    if len(text) > MAX_PREVIEW_CHARS:
        return text[:MAX_PREVIEW_CHARS], True
    return text, truncated
