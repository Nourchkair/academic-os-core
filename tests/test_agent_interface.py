from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from academia_os.activity import ActivityLog
from academia_os.config import save_config
from academia_os.domain import Deadline, DomainProjection, Evidence
from academia_os.processing import ProcessingStore
from academia_os.review import ReviewQueue
from tests.test_agent_neutral_core import minimal_config

ROOT = Path(__file__).resolve().parents[1]


def prepared_workspace(tmp_path: Path) -> tuple[dict, Path, Path]:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "05_REFERENCE").mkdir()
    (course / "06_KNOWLEDGE").mkdir()
    (course / "01_COURSE" / "Course_Status.md").write_text("# Status\n- [ ] Read Week 4\n- [x] Attend seminar\n", encoding="utf-8")
    reading = course / "05_REFERENCE" / "week-4-reading.md"
    reading.write_text("# Week 4 Reading\nPrivate source content stays out of context.", encoding="utf-8")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    return config, root, profile


def run_cli(profile: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_agent_context_is_bounded_and_composes_existing_state(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    course = root / "Fall 2026" / "POL 2103 - Politics"
    projection = DomainProjection(root / ".academia" / "domain.json")
    projection.upsert(
        Deadline(
            id="essay-deadline",
            course_id=course.name,
            title="Research Essay",
            date="2026-10-19",
            time=None,
            type="assignment",
            evidence=Evidence(
                source="Syllabus",
                source_path=str(course / "01_COURSE" / "syllabus.md"),
                provenance="ORIGINAL",
                confidence="current-confirmed",
                authority="course syllabus",
            ),
        )
    )
    queue = ReviewQueue(root / ".academia" / "review.json")
    queue.add(
        kind="deadline_conflict",
        title="Research Essay deadline needs a decision",
        course=course.name,
        details={
            "question": "Which deadline should Academia keep for the Research Essay?",
            "why_this_needs_human_input": "Two academic sources disagree.",
            "current_value": "2026-10-19",
            "proposed_value": "2026-10-22",
            "evidence": ["Syllabus page 2", "Instructor announcement"],
            "choices": [
                {"id": "keep_current", "label": "Keep October 19", "effect": "No domain value will change."},
                {"id": "use_new", "label": "Use October 22", "effect": "Update after verification."},
            ],
        },
    )
    ActivityLog(root / ".academia" / "activity.jsonl").append(
        event_type="file.imported",
        title="Imported week 4 reading",
        course=course.name,
        source="Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md",
        actor="agent:codex",
    )

    result = run_cli(profile, "agent", "context", "--scope", "course", "--course", course.name, "--detail", "compact", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["schema_version"] == 1
    assert value["scope"] == {"kind": "course", "semester": "Fall 2026", "course_id": course.name}
    assert value["current_state"]["open_tasks"][0]["title"] == "Read Week 4"
    assert value["current_state"]["next_deadlines"][0]["title"] == "Research Essay"
    assert value["attention"]["needs_human_input"][0]["question"].startswith("Which deadline")
    assert any(item["relative_path"].endswith("week-4-reading.md") for item in value["sources"]["library_items"])
    assert "content" not in json.dumps(value)
    assert "Private source content stays out of context." not in result.stdout
    assert value["recent_changes"][0]["actor"] == "agent:codex"
    assert config["academic"]["root_directory"] == str(root)


def test_agent_attention_contract_has_human_question_and_choices(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    item = ReviewQueue(root / ".academia" / "review.json").add(
        kind="source_verification",
        title="Verify reading edition",
        course="POL 2103 - Politics",
        details={"evidence": "The local copy has no edition metadata."},
    )

    result = run_cli(profile, "agent", "attention", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["schema_version"] == 1
    assert value["count"] == 1
    attention = value["items"][0]
    assert attention["id"] == item.id
    assert attention["kind"] == "source_verification"
    assert attention["question"] == "Verify reading edition"
    assert attention["why_this_needs_human_input"] == "The local copy has no edition metadata."
    assert isinstance(attention["evidence"], list)
    assert attention["status"] == "open"
    assert "choices" in attention


def test_agent_changes_cursor_is_idempotent(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    activity = ActivityLog(root / ".academia" / "activity.jsonl")
    first = activity.append(event_type="artifact.created", title="Study guide created", course="POL 2103 - Politics", actor="agent:unknown")
    activity.append(event_type="file.imported", title="Reading imported", course="POL 2103 - Politics", actor="user")

    initial = run_cli(profile, "agent", "changes", "--json")
    assert initial.returncode == 0, initial.stderr
    initial_value = json.loads(initial.stdout)
    assert initial_value["count"] == 2
    assert initial_value["changes"][0]["id"] == first.id
    cursor = initial_value["next_cursor"]
    assert cursor

    repeat = run_cli(profile, "agent", "changes", "--since", cursor, "--json")
    assert repeat.returncode == 0, repeat.stderr
    repeat_value = json.loads(repeat.stdout)
    assert repeat_value["changes"] == []
    assert repeat_value["next_cursor"] == cursor


def test_agent_changes_cursor_advances_one_page_at_a_time(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    activity = ActivityLog(root / ".academia" / "activity.jsonl")
    first = activity.append(event_type="one", title="One")
    second = activity.append(event_type="two", title="Two")
    third = activity.append(event_type="three", title="Three")

    page_one = run_cli(profile, "agent", "changes", "--limit", "1", "--json")
    assert page_one.returncode == 0, page_one.stderr
    page_one_value = json.loads(page_one.stdout)
    assert page_one_value["changes"][0]["id"] == first.id
    assert page_one_value["next_cursor"] == first.id

    page_two = run_cli(profile, "agent", "changes", "--limit", "1", "--since", first.id, "--json")
    assert page_two.returncode == 0, page_two.stderr
    page_two_value = json.loads(page_two.stdout)
    assert page_two_value["changes"][0]["id"] == second.id
    assert page_two_value["next_cursor"] == second.id

    page_three = run_cli(profile, "agent", "changes", "--limit", "1", "--since", second.id, "--json")
    assert page_three.returncode == 0, page_three.stderr
    assert json.loads(page_three.stdout)["changes"][0]["id"] == third.id


def test_agent_capabilities_are_machine_readable_and_categorized(tmp_path: Path) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    result = run_cli(profile, "agent", "capabilities", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert set(value) >= {"schema_version", "allowed_directly", "approval_required", "prohibited"}
    allowed_ids = {item["id"] for item in value["allowed_directly"]}
    prohibited_ids = {item["id"] for item in value["prohibited"]}
    assert "read_structured_context" in allowed_ids
    assert "create_ai_generated_artifact" in allowed_ids
    assert "school_submission" in prohibited_ids
    assert "authentication" in prohibited_ids


def test_agent_context_rejects_unknown_course_without_dumping_workspace(tmp_path: Path) -> None:
    _, _, profile = prepared_workspace(tmp_path)

    result = run_cli(profile, "agent", "context", "--scope", "course", "--course", "UNKNOWN", "--json")

    assert result.returncode == 2
    value = json.loads(result.stdout)
    assert value["type"] == "KeyError"
    assert "UNKNOWN" in value["error"]


def test_context_does_not_expose_processing_content_or_operational_paths(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    processing = ProcessingStore(root / ".academia" / "processing.json")
    source = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX" / "raw.pdf"
    source.parent.mkdir()
    source.write_bytes(b"raw")
    record = processing.detect(source, signature="3:1")
    processing.begin(record.id, lease_seconds=60)
    processing.fail(record.id, "parser unavailable")

    result = run_cli(profile, "agent", "context", "--detail", "compact", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["attention"]["failed_processing"][0]["id"] == record.id
    assert ".academia" not in json.dumps(value["sources"])


def test_agent_read_context_does_not_create_operational_state_or_expose_absolute_source_paths(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    before = {path.relative_to(root).as_posix() for path in root.rglob("*")}

    result = run_cli(profile, "agent", "context", "--scope", "course", "--course", "POL 2103 - Politics", "--detail", "compact", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    after = {path.relative_to(root).as_posix() for path in root.rglob("*")}
    assert after == before
    serialized = json.dumps(value)
    assert str(root) not in serialized
    assert ".academia" not in serialized
    assert all(not Path(str(task["id"]).split(":", 1)[0]).is_absolute() for task in value["current_state"]["open_tasks"])
