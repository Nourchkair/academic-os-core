from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from academia_os.actions import ActionStore
from academia_os.activity import ActivityLog
from academia_os.brief import build_daily_brief
from academia_os.config import save_config
from academia_os.domain import DomainProjection, Evidence, Reading
from academia_os.extraction.reconcile import execute_domain_change
from academia_os.review import ReviewQueue
from academia_os.source_health import build_source_health, propose_reading_verification
from academia_os.study import StudyService
from academia_os.study.schedule import schedule_blocks
from academia_os.workflow import ApprovalWorkflow
from tests.test_agent_neutral_core import minimal_config


@pytest.fixture
def phase4_workspace(tmp_path: Path):
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "05_REFERENCE").mkdir()
    source = course / "05_REFERENCE" / "week-4-reading.md"
    source.write_text("# Week 4 Reading\n\nSovereignty is supreme authority within a territory.\n", encoding="utf-8")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    source_id = source.relative_to(root).as_posix()
    projection = DomainProjection(root / ".academia" / "domain.json")
    projection.upsert(Reading(
        id="reading-week-4",
        course_id=course.name,
        title="Week 4 Reading",
        week_or_topic="Sovereignty",
        author=None,
        edition=None,
        chapter=None,
        pages=None,
        doi=None,
        isbn=None,
        required=True,
        verification_result="NOT RETRIEVED",
        evidence=Evidence(
            source="Course syllabus",
            source_path=source_id,
            provenance="ORIGINAL",
            confidence="likely",
            authority="course syllabus",
            source_hash=__import__("hashlib").sha256(source.read_bytes()).hexdigest(),
        ),
    ))
    return config, root, course, source, source_id, profile


def test_brief_composes_existing_state_and_source_health(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    from academia_os.workspace import build_workspace_snapshot
    snapshot = build_workspace_snapshot(config, persist=False)
    service = StudyService(root, "Fall 2026", course.name)
    service.set_reading_status(reading_id="reading-week-4", status="read", title="Week 4 Reading")
    ReviewQueue(root / ".academia" / "review.json").add(kind="deadline_conflict", title="Deadline needs a decision", course=course.name)
    brief = build_daily_brief(config, snapshot, now=datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc))
    assert brief["schema_version"] == 1
    assert brief["date"] == "2026-11-18"
    assert brief["decisions"]["reviews"] == 1
    assert brief["sources"]["totals"]["assigned_readings"] == 1
    assert brief["sources"]["totals"]["readings_completed"] == 1
    assert any(priority["kind"] == "review" for priority in brief["priorities"])
    assert brief["advisory"] is True


def test_schedule_places_blocks_around_calendar_events(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    from academia_os.workspace import build_workspace_snapshot
    snapshot = build_workspace_snapshot(config, persist=False)
    snapshot["tasks"] = [{
        "id": "domain:assignment:quiz",
        "title": "Quiz 3",
        "completed": False,
        "course": course.name,
        "source": "syllabus",
        "confidence": "likely",
        "due_date": "2026-11-19",
    }]
    result = schedule_blocks(
        config,
        snapshot,
        minutes=60,
        days=2,
        start_time="09:00",
        end_time="17:00",
        block_minutes=30,
        calendar_events=[{
            "summary": "Class",
            "start": {"dateTime": "2026-11-18T09:00:00Z"},
            "end": {"dateTime": "2026-11-18T12:00:00Z"},
        }],
        now=datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc),
    )
    assert result["minutes_scheduled"] > 0
    assert result["minutes_scheduled"] <= 60
    assert result["calendar_checked"] is True
    starts = [datetime.fromisoformat(block["start"]) for block in result["blocks"]]
    assert all(start.hour >= 12 or start.date() > datetime(2026, 11, 18).date() for start in starts)
    assert result["calendar_changes"] is False


def test_source_health_links_reading_exam_and_read_status(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    from academia_os.workspace import build_workspace_snapshot
    snapshot = build_workspace_snapshot(config, persist=False)
    service = StudyService(root, "Fall 2026", course.name)
    service.set_reading_status(reading_id="reading-week-4", source_id=source_id, status="read", title="Week 4 Reading")
    service.exam({"title": "Midterm", "date": "2026-11-25", "topics": ["Sovereignty"], "source_ids": [source_id]})
    context = service.context(source_ids=[source_id])
    service.annotate(context["chunks"][0], note="Read the chapter", kind="read", topic="Sovereignty")
    health = build_source_health(config, snapshot)
    course_health = next(item for item in health["courses"] if item["course_id"] == course.name)
    reading = next(item for item in course_health["readings"] if item["reading_id"] == "reading-week-4")
    assert reading["source_id"] == source_id
    assert reading["readable"] is True
    assert reading["read_status"] == "read"
    assert reading["stale"] is False
    assert course_health["exams"][0]["covered_topics"] == 1
    assert course_health["exams"][0]["uncovered_topics"] == []
    assert course_health["exams"][0]["sources"][0]["read_status"] == "read"


def test_reading_verification_creates_a_two_stage_domain_change(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    from academia_os.workspace import build_workspace_snapshot
    snapshot = build_workspace_snapshot(config, persist=False)
    proposal = propose_reading_verification(
        config,
        snapshot,
        course_id=course.name,
        reading_id="reading-week-4",
        requested={"title": "Week 4 Reading", "author": "A. Author", "isbn": "978-1-2345-6789-0"},
        retrieved={"title": "Week 4 Reading", "author": "A. Author", "isbn": "978-1-2345-6789-0"},
    )
    assert proposal["status"] == "approval_required"
    assert proposal["result"] == "EXACT MATCH — HIGH CONFIDENCE"
    queue = ReviewQueue(root / ".academia" / "review.json")
    item = queue.get(proposal["review_id"])
    assert item.kind == "reading_verification"
    workflow = ApprovalWorkflow(
        actions=ActionStore(root / ".academia" / "actions.json"),
        reviews=queue,
        activity=ActivityLog(root / ".academia" / "activity.jsonl"),
        courses=snapshot["courses"],
    )
    workflow.decide_review(item.id, "accept_match")
    workflow.execute_approved(item.action_proposal_id, lambda action: execute_domain_change(action, DomainProjection(root / ".academia" / "domain.json")))
    stored = DomainProjection(root / ".academia" / "domain.json").get("reading", "reading-week-4")
    assert stored["verification_result"] == "EXACT MATCH — HIGH CONFIDENCE"
    assert stored["evidence"]["last_verified_at"]


def test_study_reading_status_is_student_owned_and_round_trips(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    service = StudyService(root, "Fall 2026", course.name)
    record = service.set_reading_status(reading_id="reading-week-4", status="reading", title="Week 4 Reading", note="Started")
    assert record["basis"] == "student-reported"
    overview = service.overview()
    assert overview["readings_in_progress"] == 1
    assert overview["readings"][0]["status"] == "reading"
    assert (course / "06_KNOWLEDGE" / "STUDY" / "study.json").is_file()


def test_phase4_cli_brief_schedule_and_verification(phase4_workspace, tmp_path: Path):
    config, root, course, source, source_id, profile = phase4_workspace
    from tests.test_agent_interface import run_cli

    brief = run_cli(profile, "brief", "--json")
    assert brief.returncode == 0, brief.stderr
    assert json.loads(brief.stdout)["schema_version"] == 1

    schedule = run_cli(profile, "study", "schedule", "--semester", "Fall 2026", "--minutes", "30", "--days", "2", "--json")
    assert schedule.returncode == 0, schedule.stderr
    assert json.loads(schedule.stdout)["calendar_changes"] is False

    reading = run_cli(profile, "study", "reading", "--course", course.name, "--reading", "reading-week-4", "--status", "read", "--json")
    assert reading.returncode == 0, reading.stderr
    assert json.loads(reading.stdout)["reading"]["status"] == "read"

    requested = tmp_path / "requested.json"
    retrieved = tmp_path / "retrieved.json"
    requested.write_text(json.dumps({"title": "Week 4 Reading", "author": "A. Author", "isbn": "978-1-2345-6789-0"}), encoding="utf-8")
    retrieved.write_text(json.dumps({"title": "Week 4 Reading", "author": "A. Author", "isbn": "978-1-2345-6789-0"}), encoding="utf-8")
    proposed = run_cli(profile, "sources", "verify-reading", "--course", course.name, "--reading", "reading-week-4", "--requested", str(requested), "--retrieved", str(retrieved), "--json")
    assert proposed.returncode == 0, proposed.stderr
    payload = json.loads(proposed.stdout)
    assert payload["status"] == "approval_required"
    review_id = payload["review_id"]
    assert run_cli(profile, "review", "decide", review_id, "accept_match", "--json").returncode == 0
    executed = run_cli(profile, "review", "execute", review_id, "--json")
    assert executed.returncode == 0, executed.stderr
    stored = DomainProjection(root / ".academia" / "domain.json").get("reading", "reading-week-4")
    assert stored["verification_result"] == "EXACT MATCH — HIGH CONFIDENCE"


def test_syllabus_sync_preview_is_side_effect_free(phase4_workspace):
    config, root, course, source, source_id, profile = phase4_workspace
    from academia_os.source_sync import sync_syllabus
    from academia_os.workspace import build_workspace_snapshot
    syllabus = course / "01_COURSE" / "syllabus.md"
    syllabus.write_text("# POL 2103 - Politics\n\n## Required Readings\n- Week 5 Reading by A. Author (pp. 1-20)\n", encoding="utf-8")
    snapshot = build_workspace_snapshot(config, persist=False)
    before = DomainProjection(root / ".academia" / "domain.json").counts()
    result = sync_syllabus(config, snapshot, course_id=course.name, source_id=syllabus.relative_to(root).as_posix())
    assert result["status"] == "preview"
    assert result["reconciliation"]["applied"] is False
    assert DomainProjection(root / ".academia" / "domain.json").counts() == before
