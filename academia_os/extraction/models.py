from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from ..domain import Evidence


class ExtractionStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED_WITHOUT_OCR = "unsupported_without_ocr"
    UNSUPPORTED_FORMAT = "unsupported_format"
    FAILED = "failed"


@dataclass(frozen=True)
class SourceSegment:
    text: str
    page: int | None = None
    section: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    index: int = 0

    @property
    def source_location(self) -> str:
        if self.page is not None:
            return f"page {self.page}"
        if self.start_line is not None and self.end_line not in {None, self.start_line}:
            return f"lines {self.start_line}-{self.end_line}"
        if self.start_line is not None:
            return f"line {self.start_line}"
        return "document"


@dataclass(frozen=True)
class SourceDocument:
    path: str
    media_type: str
    segments: tuple[SourceSegment, ...]
    extraction_method: str
    content_hash: str
    status: ExtractionStatus = ExtractionStatus.SUPPORTED
    warnings: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()

    @property
    def full_text(self) -> str:
        return "\n".join(segment.text for segment in self.segments)


@dataclass(frozen=True)
class CandidateFact:
    kind: str
    entity_type: str
    entity: dict[str, Any]
    evidence: Evidence
    confidence: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractionResult:
    source: SourceDocument
    source_type: str
    extracted_at: str
    candidates: tuple[CandidateFact, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    identity_status: str = "unknown"

    @property
    def status(self) -> ExtractionStatus:
        return self.source.status

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": asdict(self.source),
            "source_type": self.source_type,
            "extracted_at": self.extracted_at,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
            "unsupported": list(self.unsupported),
            "identity_status": self.identity_status,
            "status": self.status.value,
        }


def extraction_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
