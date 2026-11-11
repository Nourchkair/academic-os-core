from __future__ import annotations

import pytest

from academia_os.assistant.contracts import (
    ASSISTANT_CONTRACT_VERSION,
    AssistantError,
    Disclosure,
    EventType,
    PermissionClass,
    RunEvent,
    RunRequest,
    Scope,
    ScopeKind,
    SideEffect,
    ToolDescriptor,
    validate_json_schema,
    validate_tool_call,
)


def descriptor(**overrides):
    value = {
        "name": "test.tool",
        "version": 1,
        "description": "test",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 10}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "permission": PermissionClass.READ_LOCAL,
        "side_effect": SideEffect.NONE,
        "disclosure": Disclosure.LOCAL_ONLY,
    }
    value.update(overrides)
    return ToolDescriptor(**value)


def test_scope_normalizes_kind_and_rejects_incomplete_scopes() -> None:
    assert Scope().as_dict() == {"kind": "workspace"}
    assert Scope(kind="course", semester="Fall 2026", course_id="POL 2103").as_dict() == {
        "kind": "course",
        "semester": "Fall 2026",
        "course_id": "POL 2103",
    }
    with pytest.raises(AssistantError, match="course scope"):
        Scope(kind="course", semester="Fall 2026")
    with pytest.raises(AssistantError, match="source scope"):
        Scope(kind="source", semester="Fall 2026")
    with pytest.raises(AssistantError, match="workspace scope"):
        Scope(kind="workspace", semester="Fall 2026")


def test_tool_descriptor_serializes_stable_contract_fields() -> None:
    value = descriptor().as_dict()
    assert value["name"] == "test.tool"
    assert value["version"] == 1
    assert value["permission"] == "read_local"
    assert value["side_effect"] == "none"
    assert value["disclosure"] == "local_only"
    assert value["idempotent"] is True
    with pytest.raises(AssistantError, match="tool name"):
        descriptor(name="")
    with pytest.raises(AssistantError, match="version"):
        descriptor(version=0)
    with pytest.raises(AssistantError, match="object schema"):
        descriptor(input_schema={"type": "string"})


def test_validate_json_schema_rejects_unknown_required_and_mistyped_values() -> None:
    schema = descriptor().input_schema
    validate_json_schema({"query": "ok"}, schema)
    with pytest.raises(AssistantError, match="required"):
        validate_json_schema({}, schema)
    with pytest.raises(AssistantError, match="unsupported field"):
        validate_json_schema({"query": "ok", "extra": 1}, schema)
    with pytest.raises(AssistantError, match="string"):
        validate_json_schema({"query": 4}, schema)
    with pytest.raises(AssistantError, match="too long"):
        validate_json_schema({"query": "x" * 11}, schema)
    with pytest.raises(AssistantError, match="one of"):
        validate_json_schema({"query": "ok"}, {**schema, "properties": {"query": {"type": "string", "enum": ["allowed"]}}})


def test_validate_json_schema_bounds_arrays_integers_and_enums() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "string"}},
            "count": {"type": "integer", "minimum": 1, "maximum": 3},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["items", "count"],
        "additionalProperties": False,
    }
    validate_json_schema({"items": ["x"], "count": 2, "mode": "a"}, schema)
    with pytest.raises(AssistantError, match="array"):
        validate_json_schema({"items": "x", "count": 2}, schema)
    with pytest.raises(AssistantError, match="integer"):
        validate_json_schema({"items": [], "count": True}, schema)
    with pytest.raises(AssistantError, match="at least"):
        validate_json_schema({"items": [], "count": 0}, schema)
    with pytest.raises(AssistantError, match="at most"):
        validate_json_schema({"items": [], "count": 4}, schema)


def test_validate_tool_call_requires_an_object() -> None:
    with pytest.raises(AssistantError, match="object"):
        validate_tool_call(descriptor(), [])
    assert validate_tool_call(descriptor(), {"query": "ok"}) == {"query": "ok"}


def test_assistant_error_is_structured_and_retryable() -> None:
    error = AssistantError("unavailable", code="provider_unavailable", details={"provider": "codex"}, retryable=True)
    assert error.to_dict() == {
        "code": "provider_unavailable",
        "message": "unavailable",
        "details": {"provider": "codex"},
        "retryable": True,
    }


def test_run_request_and_events_validate_bounded_lifecycle() -> None:
    request = RunRequest(messages=({"role": "user", "content": "hello"},), scope=Scope())
    assert request.max_iterations == 8
    with pytest.raises(AssistantError, match="message"):
        RunRequest(messages=(), scope=Scope())
    with pytest.raises(AssistantError, match="roles"):
        RunRequest(messages=({"role": "system", "content": "no"},), scope=Scope())
    with pytest.raises(AssistantError, match="max_iterations"):
        RunRequest(messages=({"role": "user", "content": "hello"},), scope=Scope(), max_iterations=0)

    event = RunEvent(run_id="run-1", sequence=0, event_type="run_started", data={"scope": "workspace"})
    assert event.as_dict()["event_type"] == "run_started"
    assert event.event_type is EventType.RUN_STARTED
    with pytest.raises(AssistantError, match="unsupported run event"):
        RunEvent(run_id="run-1", sequence=0, event_type="not-real")


def test_contract_version_is_explicit() -> None:
    assert ASSISTANT_CONTRACT_VERSION == 1
