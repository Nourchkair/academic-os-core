from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.assistant.contracts import Disclosure, PermissionClass, Scope, SideEffect, ToolDescriptor
from academia_os.assistant.policy import (
    PolicyDenied,
    authorize_tool,
    course_ids_in_scope,
    policy_context,
    resolve_course,
    source_scope,
    validate_scope,
)
from academia_os.workspace import build_workspace_snapshot
from tests.test_agent_interface import prepared_workspace


def descriptor(**overrides):
    value = {
        "name": "test.tool",
        "version": 1,
        "description": "test",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "permission": PermissionClass.READ_LOCAL,
        "side_effect": SideEffect.NONE,
        "disclosure": Disclosure.LOCAL_ONLY,
    }
    value.update(overrides)
    return ToolDescriptor(**value)


def context_for(tmp_path: Path, *, hosted: bool = False):
    config, root, _ = prepared_workspace(tmp_path)
    (root / "Fall 2026" / "POL 2103 - Policy" / "01_COURSE").mkdir(parents=True)
    (root / "Fall 2026" / "HIS 2101 - History" / "01_COURSE").mkdir(parents=True)
    snapshot = build_workspace_snapshot(config, persist=False)
    return policy_context(snapshot, hosted_model_allowed=hosted), root


def test_policy_context_resolves_only_exact_courses(tmp_path: Path) -> None:
    policy, _ = context_for(tmp_path)
    assert policy.course_ids == {"POL 2103 - Politics", "POL 2103 - Policy", "HIS 2101 - History"}
    assert resolve_course(policy, "Politics")["id"] == "POL 2103 - Politics"
    with pytest.raises(PolicyDenied, match="not found"):
        resolve_course(policy, "POL")
    with pytest.raises(PolicyDenied, match="ambiguous"):
        resolve_course(policy, "POL 2103")


def test_scope_validation_rejects_unknown_semester_and_cross_course_source(tmp_path: Path) -> None:
    policy, _ = context_for(tmp_path)
    validate_scope(Scope(), policy)
    validate_scope(Scope(kind="semester", semester="Fall 2026"), policy)
    validate_scope(Scope(kind="course", semester="Fall 2026", course_id="POL 2103 - Politics"), policy)

    with pytest.raises(PolicyDenied, match="semester"):
        validate_scope(Scope(kind="semester", semester="Winter 2027"), policy)
    with pytest.raises(PolicyDenied, match="not found"):
        validate_scope(Scope(kind="course", semester="Fall 2026", course_id="UNKNOWN"), policy)
    with pytest.raises(PolicyDenied, match="does not belong"):
        validate_scope(
            Scope(
                kind="source",
                semester="Fall 2026",
                course_id="HIS 2101 - History",
                source_id="Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md",
            ),
            policy,
        )


def test_source_scope_accepts_course_and_semester_files(tmp_path: Path) -> None:
    policy, root = context_for(tmp_path)
    course_source = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"
    semester_source = "Fall 2026/semester.md"
    (root / "Fall 2026" / "semester.md").write_text("# Semester\n", encoding="utf-8")

    assert source_scope(policy, course_source, course_id="POL 2103 - Politics").source_id == course_source
    assert source_scope(policy, semester_source).source_id == semester_source
    with pytest.raises(PolicyDenied, match="hidden or parent"):
        source_scope(policy, "Fall 2026/.academia/index.json")


def test_authorization_allows_local_reads_and_denies_writes_or_prohibited_tools(tmp_path: Path) -> None:
    policy, _ = context_for(tmp_path)
    scope = Scope(kind="course", semester="Fall 2026", course_id="POL 2103 - Politics")

    assert authorize_tool(descriptor(), scope, policy).allowed is True
    write = descriptor(permission=PermissionClass.WRITE_LOCAL, side_effect=SideEffect.CREATE)
    decision = authorize_tool(write, scope, policy)
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert authorize_tool(descriptor(permission=PermissionClass.PROHIBITED), scope, policy).allowed is False
    assert authorize_tool(descriptor(requires_approval=True), scope, policy).allowed is False


def test_authorization_reports_hosted_disclosure_without_blocking_local_reads(tmp_path: Path) -> None:
    local_policy, _ = context_for(tmp_path / "local", hosted=False)
    hosted_policy, _ = context_for(tmp_path / "hosted", hosted=True)
    scope = Scope(kind="course", semester="Fall 2026", course_id="POL 2103 - Politics")
    source_tool = descriptor(disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE)

    local = authorize_tool(source_tool, scope, local_policy)
    assert local.allowed is True
    assert local.hosted_disclosure_allowed is False
    assert authorize_tool(source_tool, scope, hosted_policy).hosted_disclosure_allowed is True


def test_course_ids_in_scope_respects_narrower_scopes(tmp_path: Path) -> None:
    policy, _ = context_for(tmp_path)
    assert course_ids_in_scope(policy, Scope()) == {"POL 2103 - Politics", "POL 2103 - Policy", "HIS 2101 - History"}
    assert course_ids_in_scope(policy, Scope(kind="course", semester="Fall 2026", course_id="POL 2103 - Politics")) == {"POL 2103 - Politics"}
    assert course_ids_in_scope(policy, Scope(kind="semester", semester="Winter 2027")) == set()
