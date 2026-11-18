"""Deterministic local daily brief composed from existing read models."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .activity import ActivityLog
from .assignment_history import apply_history_to_tasks, list_assignment_history
from .intake import IntakeService
from .processing import ProcessingStore
from .review import ReviewQueue
from .source_health import PENDING_INTAKE_STATUSES, build_source_health
from .study import StudyService


def _relative_source(value: Any, root: Path) -> Any:
    if not isinstance(value, str):
        return value
    try:
        path = Path(value).expanduser().resolve()
        return path.relative_to(root).as_posix()
    except (OSError, ValueError):
        return value


def _today(config: dict[str, Any], now: datetime | None = None) -> tuple[datetime, str]:
    zone = ZoneInfo(str(config["academic"]["timezone"]))
    current = (now or datetime.now(zone)).astimezone(zone)
    return current, current.date().isoformat()


def build_daily_brief(config: dict[str, Any], snapshot: dict[str, Any], *, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    if not 1 <= days <= 14:
        raise ValueError("brief window must be 1–14 days")
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    current, today = _today(config, now)
    cutoff = (current + timedelta(days=days)).date().isoformat()
    tasks = list(snapshot.get("tasks", []))
    for course in snapshot.get("courses", []):
        tasks = apply_history_to_tasks(tasks, list_assignment_history(root, str(snapshot["semester"]), str(course["id"])), course_name=str(course.get("name")))
    open_tasks = [
        {**task, "source": _relative_source(task.get("source"), root)}
        for task in tasks
        if not task.get("completed") and task.get("due_date") and str(task["due_date"]) <= cutoff
    ]
    open_tasks.sort(key=lambda task: (str(task.get("due_date") or "9999"), str(task.get("due_time") or ""), str(task.get("title") or "")))
    reviews = ReviewQueue(root / ".academia" / "review.json").list()
    intake = IntakeService(root, str(snapshot["semester"])).list_candidates()
    pending_intake = [
        candidate for candidate in intake.get("candidates", [])
        if (candidate.get("display_status") or candidate.get("status")) in PENDING_INTAKE_STATUSES
    ]
    processing = ProcessingStore(root / ".academia" / "processing.json").list()
    pending_processing = [record for record in processing if record.status.value in {"DETECTED", "PENDING", "PROCESSING", "VERIFIED"}]
    failed_processing = [record for record in processing if record.status.value == "FAILED"]
    study = []
    due_study = 0
    exams = []
    for course in snapshot.get("courses", []):
        service = StudyService(root, str(snapshot["semester"]), str(course["id"]))
        overview = service.overview()
        due_study += int(overview.get("due_count", 0))
        study.append({
            "course_id": course.get("id"),
            "course_name": course.get("name"),
            "due_count": overview.get("due_count", 0),
            "set_count": len(overview.get("sets", [])),
            "exam_count": len(overview.get("exams", [])),
        })
        for exam in overview.get("exams", []):
            if exam.get("date") and today <= exam["date"] <= (current + timedelta(days=14)).date().isoformat():
                exams.append({"course_id": course.get("id"), "title": exam.get("title"), "date": exam.get("date"), "exam_id": exam.get("id")})
    exams.sort(key=lambda exam: str(exam.get("date") or "9999"))
    sources = build_source_health(config, snapshot)
    study_blocks = []
    try:
        from .study.schedule import schedule_blocks
        study_blocks = schedule_blocks(config, snapshot, minutes=60, days=1, block_minutes=30, calendar_events=None)["blocks"]
    except (ValueError, KeyError):
        study_blocks = []
    priorities = []
    for review in reviews[:2]:
        priorities.append({"kind": "review", "title": review.title, "detail": "Waiting for your decision", "action": "changes"})
    for candidate in pending_intake[:2]:
        priorities.append({"kind": "intake", "title": candidate.get("entity_title") or "Intake candidate", "detail": "Candidate fact waiting for review", "action": "changes"})
    for task in open_tasks[:3]:
        priorities.append({"kind": "task", "title": task.get("title"), "detail": f"Due {task.get('due_date')}" + (f" · {task.get('course')}" if task.get("course") else ""), "action": "planner"})
    if due_study:
        priorities.append({"kind": "study", "title": f"{due_study} practice item{'s' if due_study != 1 else ''} due", "detail": "From your saved review schedule", "action": "planner"})
    if sources["totals"]["missing_sources"] or sources["totals"]["stale_sources"] or sources["totals"]["unverified_readings"]:
        priorities.append({
            "kind": "sources",
            "title": "Source coverage needs attention",
            "detail": f"{sources['totals']['missing_sources']} missing · {sources['totals']['stale_sources']} stale · {sources['totals']['unverified_readings']} unverified",
            "action": "courses",
        })
    attention_count = len(reviews) + len(pending_intake) + len(failed_processing) + due_study
    headline = "You're clear for today" if attention_count == 0 else (
        "One thing needs attention" if attention_count == 1 else f"{attention_count} things need attention"
    )
    activity = ActivityLog(root / ".academia" / "activity.jsonl").list()
    return {
        "schema_version": 1,
        "generated_at": current.isoformat(),
        "date": today,
        "timezone": str(current.tzinfo),
        "semester": snapshot["semester"],
        "student": config.get("student", {}).get("name", ""),
        "headline": headline,
        "priorities": priorities[:8],
        "deadlines": open_tasks[:5],
        "open_tasks": open_tasks,
        "decisions": {
            "reviews": len(reviews),
            "intake": len(pending_intake),
            "processing": len(pending_processing),
            "failed_processing": len(failed_processing),
        },
        "study": {"due_count": due_study, "courses": study, "exams": exams[:5], "blocks": study_blocks},
        "sources": sources,
        "activity_cursor": activity[0].id if activity else None,
        "advisory": True,
        "note": "This brief is derived from recorded local data. It does not contact external services, change academic values, or create calendar events.",
    }
