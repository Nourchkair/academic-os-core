from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.domain import Deadline, DomainProjection, Evidence, Reading


def _evidence(tmp_path: Path, *, confidence: str = "current-confirmed") -> Evidence:
    source = tmp_path / "Syllabus.pdf"
    source.write_bytes(b"synthetic evidence")
    return Evidence(
        source="Syllabus.pdf",
        source_path=str(source),
        source_location="page 2",
        provenance="ORIGINAL",
        confidence=confidence,
        authority="official",
    )


def test_domain_projection_persists_entities_with_evidence_and_nulls(tmp_path: Path) -> None:
    projection = DomainProjection(tmp_path / ".academia" / "domain.json")
    deadline = Deadline(
        id="deadline-1",
        course_id="HIS 101 - History",
        title="Assignment 2",
        date="2026-10-11",
        time=None,
        type="assignment",
        evidence=_evidence(tmp_path),
    )
    reading = Reading(
        id="reading-1",
        course_id="HIS 101 - History",
        title="Archives and Memory",
        week_or_topic="Week 4",
        author="Smith",
        edition=None,
        chapter="2",
        pages=None,
        doi=None,
        isbn=None,
        required=True,
        verification_result="NOT RETRIEVED",
        evidence=_evidence(tmp_path, confidence="unverified"),
    )

    projection.upsert(deadline)
    projection.upsert(reading)

    restored = DomainProjection(tmp_path / ".academia" / "domain.json")
    deadlines = restored.list("deadline")
    readings = restored.list("reading")
    assert deadlines[0]["title"] == "Assignment 2"
    assert deadlines[0]["evidence"]["source_path"].endswith("Syllabus.pdf")
    assert readings[0]["edition"] is None
    assert readings[0]["verification_result"] == "NOT RETRIEVED"


def test_domain_projection_rejects_entities_without_source_evidence(tmp_path: Path) -> None:
    projection = DomainProjection(tmp_path / "domain.json")
    deadline = Deadline(
        id="deadline-1",
        course_id="HIS 101 - History",
        title="Assignment 2",
        date="2026-10-11",
        time=None,
        type="assignment",
        evidence=Evidence(source="", source_path="", authority="unknown"),
    )

    with pytest.raises(ValueError, match="source_path"):
        projection.upsert(deadline)


def test_domain_projection_rejects_operational_state_evidence(tmp_path: Path) -> None:
    projection = DomainProjection(tmp_path / "domain.json")
    deadline = Deadline(id="deadline-1", course_id="HIS 101", title="Assignment 2", date="2026-10-11", time=None, type="assignment", evidence=Evidence(source="processing.json", source_path=str(tmp_path / ".academia" / "processing.json"), authority="unknown"))
    with pytest.raises(ValueError, match="operational state"):
        projection.upsert(deadline)


def test_domain_projection_upsert_is_idempotent_by_entity_id(tmp_path: Path) -> None:
    projection = DomainProjection(tmp_path / "domain.json")
    first = Deadline(id="deadline-1", course_id="HIS 101 - History", title="Assignment 2", date="2026-10-08", time=None, type="assignment", evidence=_evidence(tmp_path))
    second = Deadline(id="deadline-1", course_id="HIS 101 - History", title="Assignment 2", date="2026-10-11", time=None, type="assignment", evidence=_evidence(tmp_path))

    projection.upsert(first)
    projection.upsert(second)

    values = projection.list("deadline")
    assert len(values) == 1
    assert values[0]["date"] == "2026-10-11"
