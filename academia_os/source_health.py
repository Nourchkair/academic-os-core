"""Read-only source intelligence for readings, exams, and source sync.

This module joins existing durable stores. It does not create a second reading,
exam, or verification database.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .actions import ActionStore, ActionType
from .activity import ActivityLog
from .domain import DomainProjection, Evidence
from .intake import IntakeService
from .library import list_material
from .processing import ProcessingStore
from .provenance import SourceVerificationResult, verify_source_metadata
from .review import ReviewQueue
from .source_identity import SourceIdentityError, fingerprint, safe_workspace_path
from .study import StudyService
from .workflow import ApprovalWorkflow

PENDING_INTAKE_STATUSES = {
    "candidate",
    "conflict",
    "resolved",
    "needs_entity",
    "needs_course",
    "needs_confirmation",
    "proposed",
    "needs_attention",
}

_READABLE_EXTENSIONS = {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(value: Any) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(token) > 1]


def _match_source(reading: Mapping[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find one conservative Library match for a domain reading.

    Title equality wins. Otherwise every distinctive title token (at least three)
    must occur in the file name. Ambiguous matches are left unmatched rather than
    guessed.
    """
    title = str(reading.get("title") or "")
    title_tokens = _tokens(title)
    if not title_tokens:
        return None
    exact = [item for item in items if " ".join(_tokens(Path(str(item.get("name") or "")).stem)) == " ".join(title_tokens)]
    if len(exact) == 1:
        return exact[0]
    if len(title_tokens) < 3:
        return None
    matches = [item for item in items if set(title_tokens) <= set(_tokens(Path(str(item.get("name") or "")).stem))]
    return matches[0] if len(matches) == 1 else None


def _source_hash(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    try:
        return fingerprint(Path(str(item["path"])))
    except (OSError, SourceIdentityError, KeyError):
        return None


def _readable(item: Mapping[str, Any] | None, processing: Mapping[str, Any] | None) -> bool:
    if not item:
        return False
    if item.get("source_note"):
        return True
    status = str((processing or {}).get("status") or item.get("processing_status") or "").upper()
    if status in {"VERIFIED", "ACKNOWLEDGED"}:
        return True
    return str(item.get("extension") or "").lower() in _READABLE_EXTENSIONS


def _reading_status(state: Mapping[str, Any], reading_id: str, source_id: str | None) -> dict[str, Any] | None:
    records = state.get("readings") if isinstance(state.get("readings"), dict) else {}
    if not isinstance(records, dict):
        return None
    record = records.get(reading_id)
    if record is None and source_id:
        record = next((item for item in records.values() if isinstance(item, dict) and item.get("source_id") == source_id), None)
    return dict(record) if isinstance(record, dict) else None


def _exam_coverage(exam: Mapping[str, Any], overview: Mapping[str, Any], readings: list[dict[str, Any]], by_source: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    read_topics = {
        str(note.get("topic") or "").casefold()
        for note in overview.get("annotations", [])
        if note.get("kind") == "read" and note.get("topic")
    }
    practice = {str(entry.get("topic") or "").casefold(): entry for entry in overview.get("topics", [])}
    topics = [str(topic) for topic in exam.get("topics", [])]
    uncovered = [
        topic for topic in topics
        if topic.casefold() not in read_topics
        and not (practice.get(topic.casefold()) or {}).get("attempt_count")
    ]
    sources = []
    for source_id in exam.get("source_ids", []):
        item = by_source.get(source_id)
        reading = next((entry for entry in readings if entry.get("source_id") == source_id), None)
        sources.append({
            "source_id": source_id,
            "name": (item or {}).get("name") or Path(source_id).name,
            "available": bool(item),
            "readable": bool(reading and reading.get("readable")),
            "read_status": (reading or {}).get("read_status", "not_recorded"),
            "stale": bool(reading and reading.get("stale")),
        })
    covered = len(topics) - len(uncovered)
    return {
        "exam_id": exam.get("id"),
        "title": exam.get("title"),
        "date": exam.get("date"),
        "topic_count": len(topics),
        "covered_topics": covered,
        "uncovered_topics": uncovered,
        "source_count": len(sources),
        "sources": sources,
        "coverage_percent": round(100 * covered / len(topics)) if topics else 0,
    }


def _sync_status(items: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        relative = str(item.get("relative_path") or "")
        matches = [
            entity for entity in entities
            if isinstance(entity.get("evidence"), dict)
            and entity["evidence"].get("source_path") == relative
        ]
        current = _source_hash(item)
        hashes = {str(entity["evidence"].get("source_hash")) for entity in matches if entity["evidence"].get("source_hash")}
        if not matches:
            status = "not_applied"
        elif current and current in hashes:
            status = "current"
        elif hashes:
            status = "changed"
        else:
            status = "unstamped"
        result.append({
            "source_id": item.get("id"),
            "name": item.get("name"),
            "relative_path": relative,
            "status": status,
            "linked_entities": len(matches),
        })
    return result


def build_source_health(config: dict[str, Any], snapshot: dict[str, Any], *, course_id: str | None = None) -> dict[str, Any]:
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    semester = str(snapshot["semester"])
    courses = [course for course in snapshot.get("courses", []) if not course_id or course.get("id") == course_id]
    library = list_material(root, semester)
    processing = {str(Path(record.source_path).expanduser().resolve()): record.__dict__ for record in ProcessingStore(root / ".academia" / "processing.json").list()}
    projection = DomainProjection(root / ".academia" / "domain.json")
    intake = IntakeService(root, semester)
    output_courses = []
    for course in courses:
        course_name = str(course.get("id"))
        entities = [entity for entity in projection.list() if entity.get("course_id") == course_name]
        readings = [entity for entity in entities if entity.get("entity_type") == "reading"]
        course_items = [item for item in library if item.get("course_id") == course_name]
        source_items = [item for item in course_items if item.get("category") in {"readings", "syllabi", "lectures", "notes"}]
        service = StudyService(root, semester, course_name)
        state = service.read()
        overview = service.overview()
        annotated_reads = {
            str(note.get("citation", {}).get("source_id"))
            for note in overview.get("annotations", [])
            if note.get("kind") == "read"
        }
        by_source = {str(item.get("id")): item for item in course_items}
        reading_rows = []
        for reading in readings:
            match = _match_source(reading, source_items)
            source_id = str(match.get("id")) if match else None
            record = _reading_status(state, str(reading.get("id")), source_id)
            if record is None and source_id and source_id in annotated_reads:
                record = {"status": "read", "basis": "study annotation"}
            evidence = reading.get("evidence") if isinstance(reading.get("evidence"), dict) else {}
            stale = bool(match and evidence.get("source_hash") and _source_hash(match) != evidence.get("source_hash"))
            exam_ids = [
                str(exam.get("id")) for exam in overview.get("exams", [])
                if source_id and source_id in exam.get("source_ids", [])
                or str(reading.get("week_or_topic") or "").casefold() in {str(topic).casefold() for topic in exam.get("topics", [])}
            ]
            reading_rows.append({
                "reading_id": reading.get("id"),
                "title": reading.get("title"),
                "author": reading.get("author"),
                "chapter": reading.get("chapter"),
                "pages": reading.get("pages"),
                "required": reading.get("required"),
                "verification_result": reading.get("verification_result") or SourceVerificationResult.NOT_RETRIEVED.value,
                "source_id": source_id,
                "source_name": (match or {}).get("name"),
                "category": (match or {}).get("category"),
                "processing_status": (match or {}).get("processing_status"),
                "extraction_status": (match or {}).get("extraction_status"),
                "readable": _readable(match, processing.get(str(Path(match["path"]).expanduser().resolve())) if match else None),
                "stale": stale,
                "read_status": (record or {}).get("status", "not_recorded"),
                "read_basis": (record or {}).get("basis"),
                "read_updated_at": (record or {}).get("updated_at"),
                "exam_ids": sorted(set(exam_ids)),
            })
        exams = [
            _exam_coverage(exam, overview, reading_rows, by_source)
            for exam in overview.get("exams", [])
        ]
        syllabus = _sync_status([item for item in course_items if item.get("category") == "syllabi"], entities)
        candidate_value = intake.list_candidates(course_id=course_name)
        pending_intake = sum(
            1 for candidate in candidate_value.get("candidates", [])
            if (candidate.get("display_status") or candidate.get("status")) in PENDING_INTAKE_STATUSES
        )
        linked = sum(1 for reading in reading_rows if reading["source_id"])
        read_count = sum(1 for reading in reading_rows if reading["read_status"] == "read")
        unverified = sum(1 for reading in reading_rows if reading["verification_result"] != SourceVerificationResult.EXACT_MATCH.value)
        missing = len(reading_rows) - linked
        stale = sum(1 for reading in reading_rows if reading["stale"])
        output_courses.append({
            "course_id": course_name,
            "course_name": course.get("name"),
            "assigned_readings": len(reading_rows),
            "linked_sources": linked,
            "readable_sources": sum(1 for reading in reading_rows if reading["readable"]),
            "readings_completed": read_count,
            "unverified_readings": unverified,
            "stale_sources": stale,
            "missing_sources": missing,
            "coverage_percent": round(100 * read_count / len(reading_rows)) if reading_rows else 0,
            "readings": reading_rows,
            "exams": exams,
            "sync": {"syllabus": syllabus, "pending_intake": pending_intake},
        })
    totals = {
        key: sum(course[key] for course in output_courses)
        for key in ("assigned_readings", "linked_sources", "readable_sources", "readings_completed", "unverified_readings", "stale_sources", "missing_sources")
    }
    totals["coverage_percent"] = round(100 * totals["readings_completed"] / totals["assigned_readings"]) if totals["assigned_readings"] else 0
    totals["pending_intake"] = sum(course["sync"]["pending_intake"] for course in output_courses)
    totals["syllabus_changed"] = sum(1 for course in output_courses for item in course["sync"]["syllabus"] if item["status"] == "changed")
    totals["syllabus_not_applied"] = sum(1 for course in output_courses for item in course["sync"]["syllabus"] if item["status"] == "not_applied")
    return {
        "schema_version": 1,
        "generated_at": _now(),
        "semester": semester,
        "courses": output_courses,
        "totals": totals,
        "notes": [
            "Reading status is student-reported. A missing record means unknown, not unread.",
            "Verification compares metadata only; an exact match is not proof of semantic correctness.",
        ],
    }


def propose_reading_verification(
    config: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    course_id: str,
    reading_id: str,
    requested: dict[str, Any],
    retrieved: dict[str, Any],
) -> dict[str, Any]:
    from .course_identity import resolve_course_identifier

    resolved = resolve_course_identifier(snapshot.get("courses", []), course_id)
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    projection = DomainProjection(root / ".academia" / "domain.json")
    reading = projection.get("reading", reading_id)
    if str(reading.get("course_id")) != str(resolved["id"]):
        raise ValueError("reading does not belong to the selected course")
    verification = verify_source_metadata(requested, retrieved)
    before = reading.get("verification_result") or SourceVerificationResult.NOT_RETRIEVED.value
    after = verification.result.value
    if before == after:
        raise ValueError("the reading already has this verification result")
    evidence_value = reading.get("evidence") if isinstance(reading.get("evidence"), dict) else {}
    source_path = str(evidence_value.get("source_path") or "")
    if not source_path:
        raise ValueError("reading has no source file to verify")
    source_file = safe_workspace_path(root, source_path)
    source_hash = fingerprint(source_file) if source_file and source_file.is_file() else None
    confidence = {
        SourceVerificationResult.EXACT_MATCH.value: "current-confirmed",
        SourceVerificationResult.PROBABLE_MATCH.value: "likely",
    }.get(after, "unverified")
    evidence = asdict(Evidence(
        source="Source metadata verification",
        source_path=source_path,
        source_location="reading metadata",
        provenance=str(evidence_value.get("provenance") or "ORIGINAL"),
        confidence=confidence,
        authority="metadata comparison",
        last_verified_at=_now(),
        source_hash=source_hash,
        reference={
            "requested": requested,
            "retrieved": retrieved,
            "verification_result": after,
            "matched_fields": list(verification.matched_fields),
            "differing_fields": list(verification.differing_fields),
        },
    ))
    effects = [
        f"change verification_result from {before} to {after}",
        "record the requested and retrieved metadata as verification evidence",
        "leave the source file and its academic values unchanged",
    ]
    state_root = root / ".academia"
    reviews = ReviewQueue(state_root / "review.json")
    workflow = ApprovalWorkflow(
        actions=ActionStore(state_root / "actions.json"),
        reviews=reviews,
        activity=ActivityLog(state_root / "activity.jsonl"),
        courses=snapshot.get("courses", []),
    )
    proposal, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title=f"Verify reading: {reading.get('title')}",
        details={
            "updates": [{
                "entity_type": "reading",
                "entity_id": reading_id,
                "field": "verification_result",
                "before": before,
                "after": after,
                "evidence": evidence,
            }],
            "entity_type": "reading",
            "entity_id": reading_id,
            "field": "verification_result",
            "before": before,
            "after": after,
            "requested": requested,
            "retrieved": retrieved,
            "verification_result": after,
            "matched_fields": list(verification.matched_fields),
            "differing_fields": list(verification.differing_fields),
            "source": source_path,
            "effects": effects,
        },
        course=str(resolved["id"]),
        priority="normal",
        review_kind="reading_verification",
        review_details={
            "requested": requested,
            "retrieved": retrieved,
            "verification_result": after,
            "matched_fields": list(verification.matched_fields),
            "differing_fields": list(verification.differing_fields),
            "question": f"Is this the correct source for {reading.get('title')}?",
            "why_this_needs_human_input": "Metadata comparison can support a match, but only the student can accept it for this reading.",
            "current_value": before,
            "proposed_value": after,
            "source": source_path,
            "effects": effects,
        },
    )
    return {
        "status": "approval_required",
        "proposal_id": proposal.id,
        "review_id": review.id,
        "result": after,
        "matched_fields": list(verification.matched_fields),
        "differing_fields": list(verification.differing_fields),
        "before": before,
        "after": after,
        "effects": effects,
    }
