from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from academia_os.actions import ActionStore, ActionType
from academia_os.processing import ProcessingStore
from academia_os.review import ReviewQueue
from academia_os.workflow import ApprovalWorkflow
from academia_os.activity import ActivityLog
from tests.test_agent_interface import prepared_workspace

ROOT = Path(__file__).resolve().parents[1]


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


def test_agent_context_and_attention_share_canonical_course_resolution(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    course = root / "Fall 2026" / "POL 2103 - Politics"
    ReviewQueue(root / ".academia" / "review.json").add(
        kind="source_verification",
        title="Verify the syllabus",
        course=course.name,
        details={"evidence": "The edition is not recorded."},
    )

    for identifier in ("POL 2103", "POL 2103 - Politics", "Politics"):
        context = run_cli(profile, "agent", "context", "--scope", "course", "--course", identifier, "--json")
        attention = run_cli(profile, "agent", "attention", "--course", identifier, "--json")
        assert context.returncode == 0, context.stderr
        assert attention.returncode == 0, attention.stderr
        assert json.loads(context.stdout)["scope"]["course_id"] == course.name
        assert json.loads(attention.stdout)["items"][0]["course"] == course.name


def test_agent_course_identifier_rejects_unknown_and_ambiguous_values(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    second = root / "Fall 2026" / "POL 2103 - Policy"
    (second / "01_COURSE").mkdir(parents=True)

    unknown = run_cli(profile, "agent", "attention", "--course", "UNKNOWN", "--json")
    ambiguous = run_cli(profile, "agent", "context", "--scope", "course", "--course", "POL 2103", "--json")

    assert unknown.returncode == 2
    assert json.loads(unknown.stdout)["type"] == "KeyError"
    assert ambiguous.returncode == 2
    assert json.loads(ambiguous.stdout)["type"] == "ValueError"
    assert "ambiguous" in json.loads(ambiguous.stdout)["error"]


def test_review_attention_choices_are_structured_executable_decisions(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    actions = ActionStore(root / ".academia" / "actions.json")
    reviews = ReviewQueue(root / ".academia" / "review.json")
    workflow = ApprovalWorkflow(actions=actions, reviews=reviews, activity=ActivityLog(root / ".academia" / "activity.jsonl"))
    _, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title="Review Research Essay deadline",
        course="POL 2103 - Politics",
        details={"before": "2026-10-19", "after": "2026-10-22"},
        review_kind="deadline_conflict",
        review_details={
            "current_value": "2026-10-19",
            "proposed_value": "2026-10-22",
            "evidence": ["syllabus.md", "announcement.md"],
        },
    )

    result = run_cli(profile, "agent", "attention", "--course", "POL 2103", "--json")

    assert result.returncode == 0, result.stderr
    item = json.loads(result.stdout)["items"][0]
    assert item["id"] == review.id
    assert item["recommended_next_actions"] == []
    assert {choice["id"] for choice in item["choices"]} == {"keep_current", "use_new"}
    for choice in item["choices"]:
        assert choice["executable"] is True
        assert choice["action"]["type"] == "review_decision"
        assert choice["action"]["review_id"] == review.id
        assert choice["action"]["decision"] == choice["id"]
    keep = next(choice for choice in item["choices"] if choice["id"] == "keep_current")
    use_new = next(choice for choice in item["choices"] if choice["id"] == "use_new")
    assert keep["action"]["requires_execution"] is False
    assert use_new["action"]["requires_execution"] is True
    assert use_new["action"]["execution"]["type"] == "review_execute"
    assert use_new["action"]["execution"]["review_id"] == review.id


def test_advisory_attention_is_not_advertised_as_executable(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    reviews = ReviewQueue(root / ".academia" / "review.json")
    reviews.add(
        kind="source_verification",
        title="Verify edition",
        course="POL 2103 - Politics",
        details={"evidence": "The source edition is missing."},
    )
    source = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX" / "failed.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"failed")
    processing = ProcessingStore(root / ".academia" / "processing.json")
    record = processing.detect(source, signature="failed")
    processing.begin(record.id)
    processing.fail(record.id, "parser unavailable")

    result = run_cli(profile, "agent", "attention", "--json")

    assert result.returncode == 0, result.stderr
    items = json.loads(result.stdout)["items"]
    verification = next(item for item in items if item["kind"] == "source_verification")
    failure = next(item for item in items if item["kind"] == "processing_failure")
    assert verification["choices"] == []
    assert any(action["id"] == "verify_source" and action["executable"] is False for action in verification["recommended_next_actions"])
    assert failure["choices"] == []
    assert any(action["id"] == "retry_processing" and action["executable"] is False for action in failure["recommended_next_actions"])


def test_context_redacts_sensitive_keys_without_destroying_academic_language(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    ReviewQueue(root / ".academia" / "review.json").add(
        kind="source_verification",
        title="Token Economics and MFA in Security Policy",
        course="POL 2103 - Politics",
        details={
            "question": "Compare Token Economics with Secret Sharing Algorithms.",
            "evidence": [{
                "description": "Cookie Policy Research and MFA in Security Policy",
                "course_title": "Token Economics",
                "access_token": "abc123",
                "password": "correct horse battery staple",
                "cookie": "session=private",
                "client_secret": "hidden",
            }],
        },
    )

    result = run_cli(profile, "agent", "attention", "--json")

    assert result.returncode == 0, result.stderr
    serialized = result.stdout
    assert "Token Economics" in serialized
    assert "Secret Sharing Algorithms" in serialized
    assert "Cookie Policy Research" in serialized
    assert "MFA in Security Policy" in serialized
    assert "abc123" not in serialized
    assert "correct horse battery staple" not in serialized
    assert "session=private" not in serialized
    assert "hidden" not in serialized
    item = json.loads(serialized)["items"][0]
    assert item["evidence"][0]["access_token"] == "[REDACTED]"
    assert item["evidence"][0]["password"] == "[REDACTED]"


def test_context_source_catalog_excludes_retired_generated_documents(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    course = root / "Fall 2026" / "POL 2103 - Politics"
    syllabus = course / "01_COURSE" / "syllabus.md"
    syllabus.write_text("SYLLABUS BODY MUST NOT APPEAR", encoding="utf-8")
    note = course / "02_WEEKS" / "week-4-notes.md"
    note.parent.mkdir()
    note.write_text("NOTE BODY MUST NOT APPEAR", encoding="utf-8")
    legacy_generated = course / "06_KNOWLEDGE" / "AI_GENERATED"
    legacy_generated.mkdir(parents=True)
    (legacy_generated / "generated-guide.md").write_text("GENERATED BODY MUST NOT APPEAR", encoding="utf-8")

    result = run_cli(profile, "agent", "context", "--scope", "course", "--course", "POL 2103", "--detail", "deep", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    catalog = value["sources"]["library_items"]
    categories = {item["category"] for item in catalog}
    assert {"syllabi", "readings", "notes"}.issubset(categories)
    assert "generated" not in categories
    for item in catalog:
        assert set(item) >= {"id", "name", "relative_path", "course_id", "category", "provenance", "source_type"}
    assert "SYLLABUS BODY MUST NOT APPEAR" not in result.stdout
    assert "NOTE BODY MUST NOT APPEAR" not in result.stdout
    assert "GENERATED BODY MUST NOT APPEAR" not in result.stdout
    assert all("AI_GENERATED" not in item["relative_path"] for item in catalog)
