"""Deterministic extraction of deadline-change candidates from announcements."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
_MONTH_FIRST = re.compile(rf"\b(?P<month>{_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{{4}}))?\b", re.IGNORECASE)
_DAY_FIRST = re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH_PATTERN})\.?(?:,?\s+(?P<year>\d{{4}}))?\b", re.IGNORECASE)
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
_SLASH = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b")
_QUOTED = re.compile(r"[\"“”'](?P<title>[^\"“”']{2,120})[\"“”']")
_CHANGE = re.compile(r"\b(moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed|new deadline|now due|due|deadline|will be on)\b", re.IGNORECASE)
_TITLE_PATTERNS = (
    re.compile(r"\b(?:moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed)\s+(?:the\s+|our\s+|my\s+)?(?P<title>.+?)\s+(?:deadline|due date)\s+(?:to|until|is now|will be)\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?)\s+(?:deadline|due date)\s+(?:moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed)\s+(?:from\s+.+?\s+)?(?:to|until)\b", re.IGNORECASE),
    re.compile(r"\b(?:deadline|due date)\s+(?:for|of)\s+(?P<title>.+?)\s+(?:is|was|has been|will be|moved|extended|postponed|rescheduled|changed)\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?)\s+(?:is|was|has been|will be)\s+(?:moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed)\s+(?:from\s+.+?\s+)?(?:to|until)\b", re.IGNORECASE),
    re.compile(r"\b(?:moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed)\s+(?!from\b)(?:the\s+|our\s+|my\s+)?(?P<title>.+?)\s+(?:to|until|is now)\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?)\s+(?:moved|moving|move|moves|extended|extending|postponed|postponing|rescheduled|rescheduling|pushed|changed)\s+from\s+.+?\s+to\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?)\s+(?:deadline|due date)\s+(?:is|is now|will be|has been|was)\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?)\s+(?:is|is now|will be)\s+(?:due|moved|extended|postponed|rescheduled|changed)\b", re.IGNORECASE),
    re.compile(r"(?P<title>.+?(?:exam|essay|quiz|assignment|project|midterm|final).+?)\s+(?:will be|is|is now)\s+(?:on|due)\b", re.IGNORECASE),
)


@dataclass
class ParsedCandidate:
    value: str | None
    entity_title: str | None
    excerpt: str
    confidence: str
    specificity: str
    warnings: list[str] = field(default_factory=list)


def _infer_year(month: int, semester: str) -> int:
    match = re.fullmatch(r"(Winter|Spring|Summer|Fall)\s+(\d{4})", semester.strip(), re.IGNORECASE)
    if match is None:
        raise ValueError("semester must use a term and four-digit year")
    term = match.group(1).title()
    year = int(match.group(2))
    if term == "Fall":
        return year if month >= 8 else year + 1
    return year if month <= 7 else year + 1


def _date_from_match(match: re.Match[str], semester: str) -> str | None:
    groups = match.groupdict()
    try:
        month_raw = str(groups.get("month") or "")
        month = int(month_raw) if month_raw.isdigit() else MONTHS[month_raw.casefold().rstrip(".")]
        day = int(groups.get("day") or 0)
        year_text = groups.get("year")
        year = int(year_text) if year_text else _infer_year(month, semester)
        return date(year, month, day).isoformat()
    except (TypeError, ValueError, KeyError):
        return None


def _date_matches(sentence: str, semester: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for pattern, kind in ((_ISO, "iso"), (_SLASH, "slash"), (_MONTH_FIRST, "month"), (_DAY_FIRST, "month")):
        for match in pattern.finditer(sentence):
            value = _date_from_match(match, semester)
            if value is None:
                continue
            if any(item["start"] < match.end() and match.start() < item["end"] for item in matches):
                continue
            prefix = sentence[max(0, match.start() - 36):match.start()].casefold()
            if re.search(r"\b(to|until|now due|new date|new deadline|moved to|extended to|postponed to|rescheduled to|or)\s*$", prefix):
                score = 4
            elif re.search(r"\b(due|deadline|on)\s*$", prefix):
                score = 2
            elif re.search(r"\bfrom\s*$", prefix):
                score = 1
            else:
                score = 0
            matches.append({
                "value": value,
                "start": match.start(),
                "end": match.end(),
                "score": score,
                "kind": kind,
                "explicit_year": bool(match.groupdict().get("year")),
            })
    return sorted(matches, key=lambda item: item["start"])


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split()).strip(" .,:;-–—\"“”'")
    cleaned = re.sub(r"^[A-Z]{2,}\s*\d{3,}[A-Z]?\s*(?:update|announcement|notice)?\s*[:\-–—]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:update|announcement|notice)\s*[:\-–—]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:the|our|my|your|that|this)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:deadline|due date)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:the|our|my|your)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" .,:;-–—\"“”'")
    if not cleaned or cleaned.casefold() in {"it", "this", "that", "assignment", "work", "deadline"}:
        return None
    if len(cleaned) > 120:
        return None
    return cleaned


def _title(sentence: str) -> str | None:
    quoted = _QUOTED.search(sentence)
    if quoted:
        title = _clean_title(quoted.group("title"))
        if title:
            return title
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(sentence)
        if match:
            title = _clean_title(match.group("title"))
            if title:
                return title
    return None


def _sentences(value: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z“\"'])", value)
    return [part.strip() for part in parts if part.strip()]


def parse_announcement(value: str, semester: str) -> tuple[list[ParsedCandidate], list[str]]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("announcement text is required")
    candidates: list[ParsedCandidate] = []
    warnings: list[str] = []
    seen: set[tuple[str | None, str | None]] = set()
    for sentence in _sentences(value):
        if _CHANGE.search(sentence) is None:
            continue
        dates = _date_matches(sentence, semester)
        if not dates:
            warnings.append(f"No explicit date was found in: {sentence[:160]}")
            continue
        top_score = max(item["score"] for item in dates)
        top = [item for item in dates if item["score"] == top_score]
        distinct = {item["value"] for item in top}
        if len(distinct) > 1:
            warnings.append(f"Multiple possible dates were found in: {sentence[:160]}")
            candidates.append(ParsedCandidate(
                value=None,
                entity_title=_title(sentence),
                excerpt=sentence[:500],
                confidence="unverified",
                specificity="unknown",
                warnings=["ambiguous_dates"],
            ))
            continue
        selected = top[0]
        title = _title(sentence)
        confidence = "likely" if re.search(r"\b(moved|extended|postponed|rescheduled|pushed|changed)\b", sentence, re.IGNORECASE) else "unverified"
        key = (title, selected["value"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(ParsedCandidate(
            value=selected["value"],
            entity_title=title,
            excerpt=sentence[:500],
            confidence=confidence,
            specificity="exact" if selected["explicit_year"] or selected["kind"] == "iso" else "exact",
            warnings=[] if title else ["missing_assessment_title"],
        ))
    if not candidates and not warnings:
        warnings.append("No deadline-change sentence was recognized.")
    return candidates, warnings
