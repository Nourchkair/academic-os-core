from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from academia_os.actions import ActionStore
from academia_os.activity import ActivityLog
from academia_os.assistant import ReadContext
from academia_os.assistant.tools.write import create_study_set, execute_import_proposal, propose_domain_change, propose_import
from academia_os.domain import Deadline, DomainProjection, Evidence
from academia_os.extraction.reconcile import execute_domain_change
from academia_os.processing import ProcessingStore
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.study import StudyService
from academia_os.workflow import ApprovalWorkflow
from tests.test_agent_interface import prepared_workspace

ROOT = Path(__file__).resolve().parents[1]


def stores(root: Path) -> tuple[ApprovalWorkflow, ActionStore, ReviewQueue]:
    state = root / ".academia"
    actions = ActionStore(state / "actions.json")
    reviews = ReviewQueue(state / "review.json")
    workflow = ApprovalWorkflow(actions=actions, reviews=reviews, activity=ActivityLog(state / "activity.jsonl"))
    return workflow, actions, reviews


def test_import_proposal_requires_approval_and_copies_nothing(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)

    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")

    assert proposal["status"] == "approval_required"
    assert proposal["source_sha256"]
    assert proposal["effects"]
    assert list(inbox.iterdir()) == []
    _, actions, reviews = stores(root)
    stored = actions.get(proposal["proposal_id"])
    assert stored.action_type == "file_copy"
    assert stored.status == "proposed"
    assert stored.details["source_path"] == str(source.resolve())
    assert stored.details["target_id"] == "Fall 2026/POL 2103 - Politics/00_INBOX"
    review = reviews.get(proposal["review_id"])
    assert review.status is ReviewStatus.OPEN
    assert review.details["proposed_destination"] == "Fall 2026/POL 2103 - Politics/00_INBOX"


def test_approved_import_executes_and_verifies(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)
    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")
    workflow, actions, reviews = stores(root)
    workflow.approve_review(proposal["review_id"])
    assert actions.get(proposal["proposal_id"]).status == "approved"

    verified = workflow.execute_approved(
        proposal["proposal_id"],
        lambda item: execute_import_proposal(item, workspace_root=root, processing=ProcessingStore(root / ".academia" / "processing.json")),
    )

    assert verified.status == "verified"
    destination = inbox / "lecture.md"
    assert destination.read_text(encoding="utf-8") == "# Lecture\n"
    assert reviews.get(proposal["review_id"]).status is ReviewStatus.RESOLVED
    acquisition = json.loads((root / ".academia" / "acquisition.json").read_text(encoding="utf-8"))
    record = acquisition["records"]["Fall 2026/POL 2103 - Politics/00_INBOX/lecture.md"]
    assert record["source_sha256"] == proposal["source_sha256"]
    assert record["provenance"] == "EXTERNAL"


def test_replayed_import_is_rejected_without_second_copy(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)
    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")
    workflow, _, _ = stores(root)
    workflow.approve_review(proposal["review_id"])
    executor = lambda item: execute_import_proposal(item, workspace_root=root)
    workflow.execute_approved(proposal["proposal_id"], executor)

    with pytest.raises(ValueError, match="already verified"):
        workflow.execute_approved(proposal["proposal_id"], executor)
    assert len(list(inbox.iterdir())) == 1


def test_changed_source_invalidates_approval_and_reopens_review(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("first", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)
    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")
    workflow, actions, reviews = stores(root)
    workflow.approve_review(proposal["review_id"])
    source.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after approval"):
        workflow.execute_approved(proposal["proposal_id"], lambda item: execute_import_proposal(item, workspace_root=root))

    assert list(inbox.iterdir()) == []
    assert actions.get(proposal["proposal_id"]).status == "failed"
    assert reviews.get(proposal["review_id"]).status is ReviewStatus.OPEN


def test_invalid_or_out_of_scope_target_is_rejected(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)

    with pytest.raises(Exception, match="00_INBOX"):
        propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics")
    with pytest.raises(Exception, match="recognized course"):
        propose_import(context, source_path=str(source), target_id="Fall 2026/UNKNOWN/00_INBOX")


def test_cli_propose_decide_execute_import(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}

    proposed = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "assistant", "propose-import", "--source", str(source), "--target", "Fall 2026/POL 2103 - Politics/00_INBOX", "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert proposed.returncode == 0, proposed.stderr
    proposal = json.loads(proposed.stdout)
    assert proposal["status"] == "approval_required"
    assert list(inbox.iterdir()) == []

    decided = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "decide", proposal["review_id"], "approve", "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert decided.returncode == 0, decided.stderr
    assert json.loads(decided.stdout)["status"] == "approved"

    executed = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "execute", proposal["review_id"], "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)["status"] == "verified"
    assert (inbox / "lecture.md").read_text(encoding="utf-8") == "# Lecture\n"


def test_study_write_tool_creates_a_cited_set(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    context = ReadContext.create(config, hosted_model_allowed=True)
    source = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"
    service = StudyService(root, "Fall 2026", "POL 2103 - Politics")
    study_context = service.context(source_ids=[source], query="Private source content", limit=4)
    chunk = study_context["chunks"][0]
    payload = {
        "title": "Week 4 recall",
        "kind": "quiz",
        "items": [{
            "kind": "multiple_choice",
            "topic": "Private content",
            "prompt": "Where does the private source content stay?",
            "options": ["In context", "In the cloud", "In chat history"],
            "answer": "In context",
            "explanation": "The selected source is the only citation.",
            "citation_ids": [chunk["id"]],
        }],
        "connections": [],
    }

    result = create_study_set(
        context,
        course="POL 2103",
        payload=payload,
        source_ids=[source],
        query="Private source content",
        limit=4,
    )

    assert result["set"]["kind"] == "quiz"
    assert result["set"]["provenance"] == "AI-GENERATED"
    assert result["coverage"]["selected_sources"] == 1
    overview = service.overview()
    assert len(overview["sets"]) == 1
    assert overview["sets"][0]["source_count"] == 1


def test_domain_write_tool_proposes_then_verifies(tmp_path: Path) -> None:
    config, root, _ = prepared_workspace(tmp_path)
    context = ReadContext.create(config, hosted_model_allowed=True)
    domain = DomainProjection(root / ".academia" / "domain.json")
    evidence_path = "Fall 2026/POL 2103 - Politics/01_COURSE/Course_Status.md"
    evidence = Evidence(
        source="Updated syllabus",
        source_path=evidence_path,
        provenance="ORIGINAL",
        confidence="current-confirmed",
        authority="course syllabus",
    )
    domain.upsert(Deadline(
        id="essay",
        course_id="POL 2103 - Politics",
        title="Research Essay",
        date="2026-10-19",
        time=None,
        type="assignment",
        evidence=evidence,
    ))

    proposed = propose_domain_change(
        context,
        course="POL 2103",
        entity_type="deadline",
        entity_id="essay",
        field="date",
        after="2026-10-22",
        evidence_source="Updated syllabus",
        evidence_path=evidence_path,
        confidence="current-confirmed",
        authority="course syllabus",
    )
    assert proposed["status"] == "approval_required"
    assert domain.get("deadline", "essay")["date"] == "2026-10-19"
    workflow, actions, reviews = stores(root)
    workflow.approve_review(proposed["review_id"])
    verified = workflow.execute_approved(
        proposed["proposal_id"],
        lambda proposal: execute_domain_change(proposal, domain),
    )
    assert verified.status == "verified"
    assert domain.get("deadline", "essay")["date"] == "2026-10-22"
    assert reviews.get(proposed["review_id"]).status is ReviewStatus.RESOLVED


def test_cli_pending_execution_list_includes_approved_actions(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)
    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")
    workflow, _, _ = stores(root)
    workflow.approve_review(proposal["review_id"])
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}

    listed = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "list", "--pending-execution", "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert listed.returncode == 0, listed.stderr
    items = json.loads(listed.stdout)
    assert [item["id"] for item in items] == [proposal["review_id"]]
    assert items[0]["status"] == "approved"


def test_cli_review_execute_runs_the_approved_import(tmp_path: Path) -> None:
    config, root, profile = prepared_workspace(tmp_path)
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    inbox.mkdir()
    source = tmp_path / "lecture.md"
    source.write_text("# Lecture\n", encoding="utf-8")
    context = ReadContext.create(config, hosted_model_allowed=True)
    proposal = propose_import(context, source_path=str(source), target_id="Fall 2026/POL 2103 - Politics/00_INBOX")
    workflow, _, _ = stores(root)
    workflow.approve_review(proposal["review_id"])

    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "execute", proposal["review_id"], "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["status"] == "verified"
    assert (inbox / "lecture.md").is_file()


def test_action_proposal_tool_requires_a_grant_and_creates_a_preview(tmp_path: Path) -> None:
    from academia_os.assistant.contracts import ToolGrant
    from academia_os.assistant.registry import invoke_granted
    from academia_os.assistant.tools.read import ReadContext
    from academia_os.actions import ActionStore
    from academia_os.config import runtime_directory
    from tests.test_agent_interface import prepared_workspace

    config, root, _ = prepared_workspace(tmp_path)
    context = ReadContext.create(config, semester="Fall 2026")
    arguments = {"action_type": "semester_create", "details": {"semester": "Winter 2027"}}

    with pytest.raises(Exception, match="not granted"):
        invoke_granted("action.propose", arguments, context, grants=ToolGrant.none())

    result = invoke_granted("action.propose", arguments, context, grants=ToolGrant(frozenset({"action.propose"})))
    assert result.data["tier"] == "inline"
    assert result.data["preview"]["changes"][0]["to"] == "Winter 2027"

    store = ActionStore(runtime_directory(config) / "actions.json")
    saved = store.get(result.data["proposal_id"])
    assert saved.action_type == "semester_create"
    assert not (root / "Winter 2027").exists()
