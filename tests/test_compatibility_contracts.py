from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from academia_os.actions import ActionStore, ActionType
from academia_os.agent import AGENT_CONTEXT_SCHEMA_VERSION, build_agent_context
from academia_os.assistant import descriptors
from academia_os.config import save_config
from academia_os.mcp_server import _TOOLS
from academia_os.review import ReviewQueue
from academia_os.workspace import build_workspace_snapshot
from tests.test_agent_interface import prepared_workspace

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "fixtures" / "contracts"


def test_assistant_read_tool_descriptors_match_the_golden_contract() -> None:
    golden = json.loads((GOLDEN / "assistant_read_tools.json").read_text(encoding="utf-8"))
    actual = [
        {key: tool[key] for key in ("name", "version", "permission", "side_effect", "disclosure")}
        for tool in descriptors()
    ]
    assert actual == golden


def test_public_mcp_tool_names_and_required_fields_match_the_golden_contract() -> None:
    golden = json.loads((GOLDEN / "mcp_tools.json").read_text(encoding="utf-8"))
    actual = [{"name": tool["name"], "required": tool["inputSchema"]["required"]} for tool in _TOOLS]
    assert actual == golden


def test_agent_context_top_level_and_attention_shapes_are_stable(tmp_path: Path) -> None:
    config, _, _ = prepared_workspace(tmp_path)
    snapshot = build_workspace_snapshot(config, persist=False)
    value = build_agent_context(config, snapshot, scope="workspace", detail="compact")

    assert value["schema_version"] == AGENT_CONTEXT_SCHEMA_VERSION == 1
    assert set(value) == {
        "schema_version",
        "generated_at",
        "detail",
        "scope",
        "workspace",
        "semester",
        "current_state",
        "attention",
        "recent_changes",
        "sources",
        "capabilities",
    }
    assert set(value["attention"]) == {
        "schema_version",
        "generated_at",
        "count",
        "items",
        "needs_human_input",
        "conflicts",
        "failed_processing",
        "pending_processing",
        "uncertain_classification",
        "important_unverified_facts",
    }
    assert set(value["scope"]) >= {"kind", "semester"}
    assert set(value["current_state"]) == {
        "courses",
        "open_tasks",
        "next_deadlines",
        "current_assignments",
        "assignment_history",
        "study",
        "relevant_readings",
    }


def test_action_and_review_wire_keys_do_not_add_public_fields(tmp_path: Path) -> None:
    actions = ActionStore(tmp_path / "actions.json")
    proposal = actions.propose(action_type=ActionType.DOMAIN_CHANGE, title="Change", details={"before": "a", "after": "b"})
    assert set(asdict(proposal)) == {
        "id",
        "action_type",
        "title",
        "details",
        "status",
        "requires_approval",
        "created_at",
        "updated_at",
        "failure_reason",
    }
    assert "operation" in proposal.details

    review = ReviewQueue(tmp_path / "review.json").add(kind="action_approval", title="Approve", details={"operational_note": "kept"})
    assert set(asdict(review)) == {
        "id",
        "kind",
        "title",
        "course",
        "details",
        "status",
        "priority",
        "created_at",
        "updated_at",
        "action_proposal_id",
    }


def test_legacy_action_and_review_records_still_load(tmp_path: Path) -> None:
    actions_path = tmp_path / "actions.json"
    actions_path.write_text(json.dumps([{
        "id": "legacy-action",
        "action_type": "domain_change",
        "title": "Legacy change",
        "details": {"before": "a", "after": "b"},
        "status": "approved",
        "requires_approval": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "failure_reason": None,
    }]), encoding="utf-8")
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps([{
        "id": "legacy-review",
        "kind": "deadline_conflict",
        "title": "Legacy review",
        "course": None,
        "details": {"current": "a", "new": "b"},
        "status": "open",
        "priority": "normal",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "action_proposal_id": "legacy-action",
    }]), encoding="utf-8")

    proposal = ActionStore(actions_path).get("legacy-action")
    assert proposal.details == {"before": "a", "after": "b"}
    started = ActionStore(actions_path).begin_execution("legacy-action")
    assert started.details["operation"]["phase"] == "executing"
    assert ReviewQueue(review_path).get("legacy-review").details == {"current": "a", "new": "b"}


def test_cli_error_envelope_remains_minimal(tmp_path: Path) -> None:
    config, _, profile = prepared_workspace(tmp_path)
    save_config(profile, config)
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "agent", "context", "--scope", "course", "--course", "UNKNOWN", "--json"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    value = json.loads(result.stdout)
    assert set(value) == {"error", "type"}
    assert value["type"] == "KeyError"
