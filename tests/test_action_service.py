from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.action_service import ActionService
from academia_os.attachment import attach_workspace


def workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "University"
    (root / "COURSE_TEMPLATE" / "01_COURSE").mkdir(parents=True)
    (root / "COURSE_TEMPLATE" / "00_INBOX").mkdir(parents=True)
    (root / "ACADEMIC_OS_RULES.md").write_text("rules", encoding="utf-8")
    semester = root / "Fall 2026"
    (semester / "00_INBOX").mkdir(parents=True)
    course = semester / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "04_READINGS").mkdir(parents=True)
    (course / "04_READINGS" / "week1.md").write_text("notes", encoding="utf-8")
    profile = tmp_path / "home" / "profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    attach_workspace(root, profile, name="Test Student", institution="Test University", timezone="UTC", semester="Fall 2026", apply=True)
    return profile, course


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def test_propose_reports_tier_preview_and_pending(tmp_path: Path) -> None:
    profile, course = workspace(tmp_path)
    service = ActionService(profile)
    root = service.root

    review = service.propose("file_trash", {"path": relative(root, course / "04_READINGS" / "week1.md")})
    assert review["tier"] == "review"
    assert review["requires_review"] is True
    assert review["preview"]["changes"][0]["from"].endswith("week1.md")

    inline = service.propose("grade_record", {
        "course_id": course.name,
        "values": {"kind": "essay", "title": "First Essay", "status": "graded", "grade": "82%"},
    })
    assert inline["tier"] == "inline"
    assert inline["requires_review"] is False

    pending = service.pending()
    assert {item["proposal_id"] for item in pending} == {review["proposal_id"], inline["proposal_id"]}


def test_inline_actions_execute_and_verify(tmp_path: Path) -> None:
    profile, course = workspace(tmp_path)
    service = ActionService(profile)
    proposed = service.propose("grade_record", {
        "course_id": course.name,
        "values": {"kind": "essay", "title": "First Essay", "status": "graded", "grade": "82%"},
    })

    result = service.execute_inline(proposed["proposal_id"])
    assert result["status"] == "verified"
    assert result["verification"]["grade"] == "82%"
    events = [event.event_type for event in service.activity.list(limit=20)]
    assert "action.executed" in events
    assert "action.verified" in events


def test_review_actions_cannot_use_the_inline_shortcut(tmp_path: Path) -> None:
    profile, course = workspace(tmp_path)
    service = ActionService(profile)
    proposed = service.propose("file_trash", {"path": relative(service.root, course / "04_READINGS" / "week1.md")})

    with pytest.raises(PermissionError):
        service.execute_inline(proposed["proposal_id"])
    assert (course / "04_READINGS" / "week1.md").is_file()


def test_discard_removes_a_pending_action(tmp_path: Path) -> None:
    profile, course = workspace(tmp_path)
    service = ActionService(profile)
    proposed = service.propose("file_trash", {"path": relative(service.root, course / "04_READINGS" / "week1.md")})

    assert service.discard(proposed["proposal_id"])["discarded"] is True
    assert service.pending() == []
    with pytest.raises(KeyError):
        service.discard(proposed["proposal_id"])


def test_semester_and_course_creation(tmp_path: Path) -> None:
    profile, _ = workspace(tmp_path)
    service = ActionService(profile)

    semester = service.propose("semester_create", {"semester": "Winter 2027"})
    assert service.execute_inline(semester["proposal_id"])["status"] == "verified"
    assert (service.root / "Winter 2027" / "00_INBOX").is_dir()

    course = service.propose("course_create", {"name": "HIS 101 - History", "semester": "Winter 2027"})
    assert service.execute_inline(course["proposal_id"])["status"] == "verified"
    assert (service.root / "Winter 2027" / "HIS 101 - History" / "01_COURSE").is_dir()

    duplicate = service.propose("course_create", {"name": "HIS 101 - History", "semester": "Winter 2027"})
    with pytest.raises(Exception, match="already exists"):
        service.execute_inline(duplicate["proposal_id"])


def test_settings_change_is_review_tier_and_writes_the_profile(tmp_path: Path) -> None:
    profile, _ = workspace(tmp_path)
    service = ActionService(profile)

    proposed = service.propose("configuration_change", {"updates": {"student.program": "Political Science"}})
    assert proposed["tier"] == "review"
    with pytest.raises(PermissionError):
        service.execute_inline(proposed["proposal_id"])

    from academia_os.action_catalog import ActionContext, execute_action

    context = ActionContext(workspace_root=service.root, state_root=service.state, semester="Fall 2026", profile_path=profile)
    result = execute_action(service.actions.get(proposed["proposal_id"]), context, actor="user")
    assert result["verified"] is True
    from academia_os.config import load_config

    assert load_config(profile)["student"]["program"] == "Political Science"
