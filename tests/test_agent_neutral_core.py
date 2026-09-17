from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from academia_os.acquisition import acquisition_defaults, browser_access_policy, capability_report
from academia_os.browser import allowed_url
from academia_os.activity import ActivityLog
from academia_os.config import CURRENT_CONFIG_VERSION, migrate_config, save_config, validate_config
from academia_os.processing import ProcessingStatus, ProcessingStore
from academia_os.provenance import ProvenanceLabel, SourceVerificationResult, verify_source_metadata
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.semester import resolve_current_semester
from academia_os.settings import update_config
from academia_os.workspace import build_workspace_snapshot


def minimal_config(tmp_path: Path) -> dict:
    return {
        "schema_version": 2,
        "student": {"name": "Alex Student", "institution": "Example University", "program": "History"},
        "academic": {
            "semester": "Fall 2026",
            "timezone": "UTC",
            "root_directory": str(tmp_path / "University OS"),
            "school_portal": "Not yet specified",
        },
        "runtime": {"install_directory": str(tmp_path / ".academic-os")},
        "preferences": {"explanation_style": "detailed", "preferred_format": "markdown", "use_visuals": True, "study_method": "active recall"},
        "integrations": {"gmail": False, "calendar": False, "drive": False, "school_portal": False},
        "automation": {"daily_brief_enabled": True, "daily_brief_time": "09:00", "inbox_processor_enabled": True, "inbox_interval_minutes": 5},
        "acquisition": {"manual_import_enabled": True, "watched_folders": [], "browser_companion_enabled": False, "browser_access_enabled": False, "advanced_browser_enabled": False, "allowed_sites": []},
        "privacy": {"browser_access_enabled": False, "allowed_sites": [], "dedicated_profile_recommended": True},
        "agents": {"hermes": {"enabled": False, "profile": "default"}, "codex": {"enabled": False}, "claude": {"enabled": False}, "chatgpt": {"enabled": False}},
    }


def test_v1_config_migrates_to_agent_neutral_v2_without_requiring_hermes(tmp_path: Path) -> None:
    legacy = {
        "schema_version": 1,
        "student": {"name": "Alex", "institution": "Example U", "program": "History"},
        "academic": {"semester": "Current Semester", "timezone": "UTC", "root_directory": str(tmp_path / "University")},
        "automation": {"daily_brief_enabled": True, "daily_brief_time": "09:00", "inbox_processor_enabled": True, "inbox_interval_minutes": 5},
    }
    migrated = migrate_config(legacy, now=datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert migrated["schema_version"] == CURRENT_CONFIG_VERSION
    assert migrated["academic"]["semester"] == "Fall 2026"
    assert "hermes" not in migrated["runtime"]
    assert migrated["agents"]["hermes"]["enabled"] is False
    assert validate_config(migrated)["schema_version"] == CURRENT_CONFIG_VERSION


def test_config_rejects_literal_current_semester_and_defaults_browser_off(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    config["academic"]["semester"] = "Current Semester"
    with pytest.raises(ValueError, match="resolved semester"):
        validate_config(config)
    defaults = acquisition_defaults()
    assert defaults["browser_access_enabled"] is False
    assert defaults["advanced_browser_enabled"] is False


def test_semester_resolution_is_date_based_and_customizable() -> None:
    assert resolve_current_semester(datetime(2026, 9, 16, tzinfo=timezone.utc)) == "Fall 2026"
    assert resolve_current_semester(datetime(2026, 2, 1, tzinfo=timezone.utc)) == "Winter 2026"
    assert resolve_current_semester(datetime(2026, 6, 1, tzinfo=timezone.utc)) == "Spring 2026"
    assert resolve_current_semester(datetime(2026, 7, 1, tzinfo=timezone.utc)) == "Summer 2026"


def test_review_queue_and_activity_log_survive_restart(tmp_path: Path) -> None:
    queue_path = tmp_path / ".academia" / "review.json"
    activity_path = tmp_path / ".academia" / "activity.jsonl"
    queue = ReviewQueue(queue_path)
    item = queue.add(kind="deadline_conflict", title="Deadline conflict", course="POL 2103", details={"current": "October 8", "new": "October 11"})
    queue.update(item.id, status=ReviewStatus.APPROVED)
    assert ReviewQueue(queue_path).get(item.id).status is ReviewStatus.APPROVED
    log = ActivityLog(activity_path)
    event = log.append(event_type="deadline.updated", title="Assignment 2 deadline updated", course="POL 2103", details={"old": "October 8", "new": "October 11"}, source="Instructor announcement", confidence="Current-confirmed")
    restored = ActivityLog(activity_path).list()
    assert restored[0].id == event.id
    assert restored[0].details["new"] == "October 11"


def test_processing_lifecycle_keeps_failures_retryable_until_acknowledged(tmp_path: Path) -> None:
    store = ProcessingStore(tmp_path / ".academia" / "processing.json")
    source = tmp_path / "syllabus.pdf"
    source.write_bytes(b"v1")
    record = store.detect(source, signature="hash-v1")
    assert record.status is ProcessingStatus.PENDING
    processing = store.begin(record.id, lease_seconds=60)
    assert processing.status is ProcessingStatus.PROCESSING
    failed = store.fail(record.id, "parser unavailable")
    assert failed.status is ProcessingStatus.FAILED
    retry = store.retry(record.id)
    assert retry.status is ProcessingStatus.PENDING
    store.begin(record.id, lease_seconds=60)
    verified = store.verify(record.id, verification={"classification": "syllabus"})
    assert verified.status is ProcessingStatus.VERIFIED
    assert store.acknowledge(record.id).status is ProcessingStatus.ACKNOWLEDGED
    assert store.pending() == []


def test_processing_stale_lease_returns_to_pending(tmp_path: Path) -> None:
    store = ProcessingStore(tmp_path / "processing.json")
    source = tmp_path / "notes.md"
    source.write_text("notes", encoding="utf-8")
    record = store.detect(source, signature="hash")
    store.begin(record.id, lease_seconds=-1)
    recovered = store.recover_stale(now=datetime.now(timezone.utc))
    assert recovered[0].status is ProcessingStatus.PENDING
    assert recovered[0].retry_count == 1


def test_provenance_and_source_verification_are_explicit() -> None:
    assert ProvenanceLabel.ORIGINAL.value == "ORIGINAL"
    assert SourceVerificationResult.EXACT_MATCH.value == "EXACT MATCH — HIGH CONFIDENCE"
    exact = verify_source_metadata({"author": "Smith", "year": 2024}, {"author": "Smith", "year": 2024})
    probable = verify_source_metadata({"author": "Smith", "year": 2024, "edition": 3}, {"author": "Smith", "year": 2024, "edition": 2})
    assert exact.result is SourceVerificationResult.EXACT_MATCH
    assert probable.result is SourceVerificationResult.PROBABLE_MATCH


def test_workspace_snapshot_is_structured_and_rebuildable(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "00_INBOX").mkdir()
    (course / "00_INBOX" / "syllabus.pdf").write_bytes(b"pdf")
    snapshot = build_workspace_snapshot(config)
    assert snapshot["semester"] == "Fall 2026"
    assert snapshot["courses"][0]["code"] == "POL 2103"
    assert snapshot["courses"][0]["inbox_count"] == 1
    index = root / ".academia" / "index.json"
    assert index.is_file()
    assert json.loads(index.read_text(encoding="utf-8"))["courses"][0]["code"] == "POL 2103"


def test_browser_capability_report_does_not_claim_unsupported_browsers() -> None:
    report = capability_report()
    assert report["chromium"]["status"] in {"supported", "available", "unsupported"}
    assert report["firefox"]["status"] == "planned"
    assert report["safari"]["status"] == "planned"


def test_browser_policy_is_opt_in_and_allowlist_is_explicit(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    assert browser_access_policy(config)["enabled"] is False
    assert allowed_url("https://brightspace.example.edu/course", ["brightspace.example.edu"])
    assert allowed_url("https://sub.brightspace.example.edu/course", ["brightspace.example.edu"])
    assert not allowed_url("https://gmail.example.edu", ["brightspace.example.edu"])


def test_settings_update_requires_approval_for_structural_changes(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    candidate, changes = update_config(config, {"student.name": "New Name"})
    assert candidate["student"]["name"] == "New Name"
    assert changes[0]["structural"] is False
    with pytest.raises(PermissionError, match="structural"):
        update_config(config, {"academic.root_directory": str(tmp_path / "Other")})
    candidate, changes = update_config(config, {"academic.root_directory": str(tmp_path / "Other")}, approve_structural=True)
    assert candidate["academic"]["root_directory"].endswith("Other")
    assert changes[0]["structural"] is True
