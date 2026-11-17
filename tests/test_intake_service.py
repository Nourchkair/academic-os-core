from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.assignment_history import add_assignment_history, list_assignment_history
from academia_os.intake import IntakeService
from academia_os.knowledge import KnowledgeService


def _workspace(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "University"
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    record = add_assignment_history(root, "Fall 2026", course.name, {
        "kind": "essay",
        "title": "Second Essay",
        "status": "planned",
        "due_date": "2026-11-12",
    })
    return root, course, record


def test_paste_preserves_source_resolves_candidate_and_bridges_to_changeset(tmp_path: Path) -> None:
    root, course, record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    result = service.submit_paste(
        text_value="My professor moved the Second Essay deadline to November 20.",
        course_id=course.name,
        source_kind="professor_announcement",
    )

    intake = result["intake"]
    source = root / intake["source_path"]
    assert source.is_file()
    assert "My professor moved the Second Essay deadline to November 20." in source.read_text()
    assert intake["status"] == "candidates_found"
    assert source.parent == course / "00_INBOX"

    candidate = result["candidates"][0]
    assert candidate["status"] == "resolved"
    assert candidate["value"] == "2026-11-20"
    assert candidate["resolution"]["assessment_id"] == f"assessment:history:{record['id']}"

    changeset = service.propose_candidate(candidate["id"])
    assert changeset["status"] == "proposed"
    assert changeset["evidence"][0]["source_path"] == intake["source_path"]
    assert changeset["conflicts"]

    knowledge = KnowledgeService(root, "Fall 2026")
    knowledge.approve_changeset(changeset["id"])
    executed = knowledge.execute_changeset(changeset["id"])
    assert executed["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"
    assert service.show_candidate(candidate["id"])["candidate"]["status"] == "proposed"


def test_duplicate_paste_returns_the_existing_intake_without_duplicate_candidates(tmp_path: Path) -> None:
    root, course, _record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    text = "My professor moved the Second Essay deadline to November 20."
    first = service.submit_paste(text_value=text, course_id=course.name)
    second = service.submit_paste(text_value=text, course_id=course.name)
    assert second["intake"]["id"] == first["intake"]["id"]
    assert len(first["candidates"]) == len(second["candidates"]) == 1
    assert second["warnings"]


def test_unresolved_title_needs_entity_then_student_resolves_it(tmp_path: Path) -> None:
    root, course, record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    result = service.submit_paste(
        text_value="The professor moved the Final Essay deadline to November 20.",
        course_id=course.name,
    )
    candidate = result["candidates"][0]
    assert candidate["status"] == "needs_entity"
    assert candidate["available_assessments"]
    with pytest.raises(ValueError, match="not ready"):
        service.propose_candidate(candidate["id"])

    resolved = service.resolve_candidate(candidate["id"], assessment_id=f"assessment:history:{record['id']}")
    assert resolved["candidate"]["status"] == "resolved"
    assert service.propose_candidate(candidate["id"])["status"] == "proposed"


def test_unresolved_course_needs_course_and_can_be_resolved(tmp_path: Path) -> None:
    root, course, record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    result = service.submit_paste(text_value="The Second Essay deadline moved to November 20.")
    candidate = result["candidates"][0]
    assert candidate["status"] == "needs_course"
    assert candidate["resolution"]["why"]
    with pytest.raises(ValueError):
        service.propose_candidate(candidate["id"])

    resolved = service.resolve_candidate(
        candidate["id"],
        course_id=course.name,
        assessment_id=f"assessment:history:{record['id']}",
    )
    assert resolved["candidate"]["status"] == "resolved"


def test_course_code_is_inferred_from_the_paste(tmp_path: Path) -> None:
    root, course, _record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    result = service.submit_paste(
        text_value="POL 2103 update: the Second Essay deadline moved to November 20."
    )
    candidate = result["candidates"][0]
    assert candidate["course_id"] == course.name
    assert candidate["status"] == "resolved"


def test_no_candidates_still_preserves_the_source(tmp_path: Path) -> None:
    root, course, _record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    result = service.submit_paste(text_value="No academic changes today.", course_id=course.name)
    assert result["intake"]["status"] == "no_candidates"
    assert result["candidates"] == []
    assert (root / result["intake"]["source_path"]).is_file()


def test_agent_can_propose_but_cannot_resolve_or_reject(tmp_path: Path) -> None:
    root, course, _record = _workspace(tmp_path)
    service = IntakeService(root, "Fall 2026")
    candidate = service.submit_paste(
        text_value="The Second Essay deadline moved to November 20.",
        course_id=course.name,
    )["candidates"][0]
    with pytest.raises(PermissionError):
        service.resolve_candidate(candidate["id"], course_id=course.name, actor="agent:codex", channel="assistant")
    with pytest.raises(PermissionError):
        service.reject_candidate(candidate["id"], actor="agent:codex", channel="assistant")
    changeset = service.propose_candidate(candidate["id"], actor="agent:codex", channel="assistant")
    assert changeset["status"] == "proposed"
