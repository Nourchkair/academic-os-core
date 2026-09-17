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
    if not differing:
        result = SourceVerificationResult.EXACT_MATCH
    elif matched and len(matched) >= max(1, len(requested) // 2):
        result = SourceVerificationResult.PROBABLE_MATCH
    else:
        result = SourceVerificationResult.MISMATCH
    return SourceVerification(result, tuple(matched), tuple(differing))
