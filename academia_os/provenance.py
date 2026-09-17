from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProvenanceLabel(str, Enum):
    ORIGINAL = "ORIGINAL"
    USER_CREATED = "USER-CREATED"
    AI_GENERATED = "AI-GENERATED"
    EXTERNAL = "EXTERNAL"


class SourceVerificationResult(str, Enum):
    EXACT_MATCH = "EXACT MATCH — HIGH CONFIDENCE"
    PROBABLE_MATCH = "PROBABLE MATCH — VERIFY MANUALLY"
    MISMATCH = "MISMATCH"
    NOT_RETRIEVED = "NOT RETRIEVED"


@dataclass(frozen=True)
class SourceVerification:
    result: SourceVerificationResult
    matched_fields: tuple[str, ...]
    differing_fields: tuple[str, ...]


IDENTITY_FIELDS = {"title", "author", "authors", "isbn", "doi", "publisher", "year", "url"}


def _has_sufficient_identity(metadata: dict[str, Any]) -> bool:
    """Require enough identity evidence before claiming an exact source match."""
    if not metadata:
        return False
    if any(str(metadata.get(key, "")).strip() for key in ("doi", "isbn")):
        return True
    title = str(metadata.get("title", "")).strip()
    url = str(metadata.get("url", "")).strip()
    if url:
        return True
    if not title:
        return False
    author = str(metadata.get("author", metadata.get("authors", ""))).strip()
    year = str(metadata.get("year", "")).strip()
    publisher = str(metadata.get("publisher", "")).strip()
    return bool(author or year or (publisher and year))


def verify_source_metadata(requested: dict[str, Any], retrieved: dict[str, Any]) -> SourceVerification:
    if not retrieved:
        return SourceVerification(SourceVerificationResult.NOT_RETRIEVED, (), tuple(sorted(requested)))
    matched: list[str] = []
    differing: list[str] = []
    for key, expected in requested.items():
        actual = retrieved.get(key)
        if actual is None:
            differing.append(key)
        elif str(actual).strip().casefold() == str(expected).strip().casefold():
            matched.append(key)
        else:
            differing.append(key)
    if not requested:
        return SourceVerification(SourceVerificationResult.NOT_RETRIEVED, (), ())
    if not differing and _has_sufficient_identity(requested) and any(field in matched for field in IDENTITY_FIELDS):
        result = SourceVerificationResult.EXACT_MATCH
    elif matched and len(matched) >= max(1, len(requested) // 2):
        result = SourceVerificationResult.PROBABLE_MATCH
    else:
        result = SourceVerificationResult.MISMATCH
    return SourceVerification(result, tuple(matched), tuple(differing))
