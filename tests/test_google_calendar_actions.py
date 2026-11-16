from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from academia_os.actions import ActionStatus, ActionStore
from academia_os.activity import ActivityLog
from academia_os.agent import build_agent_attention
from academia_os.config import load_config
from academia_os.connectors import google
from academia_os.connectors.google_actions import (
    execute_calendar_change,
    propose_calendar_create,
    propose_calendar_update,
)
from academia_os import cli
from academia_os.review import ReviewQueue, ReviewStatus
from academia_os.workflow import ApprovalWorkflow
from academia_os.workspace import build_workspace_snapshot
from tests.test_google_connector import FakeGoogleServer, MemoryGoogleStore, _configure
from tests.test_agent_interface import prepared_workspace


def _workflow(root: Path) -> tuple[ApprovalWorkflow, ActionStore, ReviewQueue, ActivityLog]:
    actions = ActionStore(root / "actions.json")
    reviews = ReviewQueue(root / "review.json")
    activity = ActivityLog(root / "activity.jsonl")
    return ApprovalWorkflow(actions=actions, reviews=reviews, activity=activity), actions, reviews, activity


def _connector(root: Path, server: FakeGoogleServer) -> google.GoogleConnector:
    store = MemoryGoogleStore()
    connector = google.GoogleConnector(root / "google.json", store=store)  # type: ignore[arg-type]
    _configure(connector, server)
    store.tokens = {
        "access_token": server.access_token,
        "refresh_token": server.refresh_token,
        "expires_at": time.time() + 3600,
    }
    return connector


def test_calendar_create_requires_review_and_is_verified_after_execution(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    connector = _connector(tmp_path, server)
    workflow, actions, reviews, activity = _workflow(tmp_path)
    event = {
        "summary": "POL 2103 study block",
        "start": "2027-02-10T14:00:00Z",
        "end": "2027-02-10T15:00:00Z",
        "location": "Library",
        "description": "Review lecture notes",
    }
    try:
        proposal, review = propose_calendar_create(workflow, connector, event)
        assert review.status is ReviewStatus.OPEN
        assert proposal.status == ActionStatus.PROPOSED.value
        assert review.details["action_type"] == "calendar_change"
        assert review.details["proposal_details"]["after"].startswith("POL 2103 study block")
        assert server.calendar_events.keys() == {"event-1"}

        workflow.approve_review(review.id)
        assert actions.get(proposal.id).status == ActionStatus.APPROVED.value
        verified = workflow.execute_approved(proposal.id, lambda item: execute_calendar_change(item, connector))
        assert verified.status == ActionStatus.VERIFIED.value
        assert reviews.get(review.id).status is ReviewStatus.RESOLVED
        assert reviews.get(review.id).details["verification"]["verified"] is True
        assert len(server.calendar_events) == 2
        assert activity.list(limit=1)[0].event_type == "action.verified"

        with pytest.raises(ValueError, match="already verified"):
            workflow.execute_approved(proposal.id, lambda item: execute_calendar_change(item, connector))
    finally:
        server.close()


def test_calendar_create_rechecks_duplicates_and_recovers_lost_create_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeGoogleServer()
    connector = _connector(tmp_path, server)
    workflow, actions, reviews, _ = _workflow(tmp_path)
    event = {
        "summary": "POL 2103 study block",
        "start": "2027-02-10T14:00:00Z",
        "end": "2027-02-10T15:00:00Z",
    }
    try:
        proposal, review = propose_calendar_create(workflow, connector, event)
        workflow.approve_review(review.id)
        original_create = connector.calendar_create

        def commit_then_lose_response(payload: dict[str, Any], *, event_id: str) -> dict[str, Any]:
            original_create(payload, event_id=event_id)
            raise google.GoogleConnectorError("simulated lost response after Google committed")

        monkeypatch.setattr(connector, "calendar_create", commit_then_lose_response)
        result = workflow.execute_approved(proposal.id, lambda item: execute_calendar_change(item, connector))
        assert result.status == ActionStatus.VERIFIED.value
        assert len(server.calendar_events) == 2
        assert reviews.get(review.id).status is ReviewStatus.RESOLVED
        monkeypatch.setattr(connector, "calendar_create", original_create)

        duplicate_event = {
            "summary": "Existing duplicate",
            "start": "2027-02-11T14:00:00Z",
            "end": "2027-02-11T15:00:00Z",
        }
        connector.calendar_create(duplicate_event, event_id="abcde12345")
        with pytest.raises(google.GoogleConnectorError, match="already exists"):
            propose_calendar_create(workflow, connector, duplicate_event)

        stale_proposal, stale_review = propose_calendar_create(workflow, connector, {
            "summary": "New event",
            "start": "2027-02-12T14:00:00Z",
            "end": "2027-02-12T15:00:00Z",
        })
        workflow.approve_review(stale_review.id)
        stale_action = actions.get(stale_proposal.id)
        # A separate matching event is inserted after approval but before the
        # executor's second duplicate check.
        connector.calendar_create({
            "summary": "New event",
            "start": "2027-02-12T14:00:00Z",
            "end": "2027-02-12T15:00:00Z",
        }, event_id="abcde67890")
        with pytest.raises(google.GoogleConnectorError, match="already exists"):
            workflow.execute_approved(stale_action.id, lambda item: execute_calendar_change(item, connector))
        assert reviews.get(stale_review.id).status is ReviewStatus.OPEN
        assert actions.get(stale_proposal.id).status == ActionStatus.FAILED.value
    finally:
        server.close()


def test_calendar_update_uses_review_etag_and_verifies_fields(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    connector = _connector(tmp_path, server)
    workflow, actions, reviews, _ = _workflow(tmp_path)
    try:
        proposal, review = propose_calendar_update(
            workflow,
            connector,
            event_id="event-1",
            patch={"summary": "Updated study session", "location": "Room 204"},
        )
        assert review.details["proposal_details"]["before"].startswith("Study session")
        assert review.details["proposal_details"]["after"].startswith("Updated study session")
        workflow.approve_review(review.id)
        verified = workflow.execute_approved(proposal.id, lambda item: execute_calendar_change(item, connector))
        assert verified.status == ActionStatus.VERIFIED.value
        saved = connector.calendar_get("event-1")
        assert saved["summary"] == "Updated study session"
        assert saved["location"] == "Room 204"
        assert actions.get(proposal.id).details["operation"]["phase"] == "verified"

        stale, stale_review = propose_calendar_update(
            workflow,
            connector,
            event_id="event-1",
            patch={"summary": "Another title"},
        )
        workflow.approve_review(stale_review.id)
        server.calendar_events["event-1"]["etag"] = '"changed-outside-academia"'
        with pytest.raises(google.GoogleConnectorError, match="changed after review"):
            workflow.execute_approved(stale.id, lambda item: execute_calendar_change(item, connector))
        assert reviews.get(stale_review.id).status is ReviewStatus.OPEN
    finally:
        server.close()


def test_calendar_update_rejects_duplicate_target_at_proposal_time(tmp_path: Path) -> None:
    server = FakeGoogleServer()
    connector = _connector(tmp_path, server)
    workflow, _, _, _ = _workflow(tmp_path)
    try:
        connector.calendar_create({
            "summary": "Duplicate session",
            "start": "2027-03-01T12:00:00Z",
            "end": "2027-03-01T13:00:00Z",
        }, event_id="abcde12345")
        with pytest.raises(google.GoogleConnectorError, match="would duplicate"):
            propose_calendar_update(
                workflow,
                connector,
                event_id="event-1",
                patch={
                    "summary": "Duplicate session",
                    "start": "2027-03-01T12:00:00Z",
                    "end": "2027-03-01T13:00:00Z",
                },
            )
    finally:
        server.close()


def test_review_execute_cli_supports_calendar_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    server = FakeGoogleServer()
    _, root, profile = prepared_workspace(tmp_path / "workspace")
    connector = _connector(tmp_path, server)
    workflow, _, reviews, _ = _workflow(root / ".academia")
    try:
        _, review = propose_calendar_create(workflow, connector, {
            "summary": "CLI calendar proposal",
            "start": "2027-04-04T10:00:00Z",
            "end": "2027-04-04T11:00:00Z",
        })
        workflow.approve_review(review.id)
        monkeypatch.setattr(google, "GoogleConnector", lambda _path: connector)
        args = cli.build_parser().parse_args([
            "--profile", str(profile), "review", "execute", review.id, "--json",
        ])

        assert cli.dispatch(args) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == ActionStatus.VERIFIED.value
        assert reviews.get(review.id).status is ReviewStatus.RESOLVED
        assert len(server.calendar_events) == 2
    finally:
        server.close()


def test_calendar_review_attention_advertises_separate_execution(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path / "workspace")
    workflow, _, _, _ = _workflow(root / ".academia")
    _, review = workflow.propose(
        action_type="calendar_change",
        title="Create a study block",
        details={
            "calendar_action": "create",
            "effects": ["Create one Google Calendar event after approval."],
            "after": "Study block · 2027-02-10 14:00 UTC",
        },
        review_kind="action_approval",
    )
    config = load_config(profile)
    snapshot = build_workspace_snapshot(config, persist=False)
    attention = build_agent_attention(config, snapshot, detail="deep")
    item = next(entry for entry in attention["items"] if entry["id"] == review.id)
    approve = next(choice for choice in item["choices"] if choice["id"] == "approve")
    assert approve["executable"] is True
    assert approve["action"]["requires_execution"] is True
    assert approve["action"]["execution"]["type"] == "review_execute"
