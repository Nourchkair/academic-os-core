"""Versioned contracts shared by the first-party assistant runtime.

These types are intentionally independent of React, Tauri, MCP, and provider
SDKs.  They describe only what the academic core is willing to accept and
return.  Invalid input fails closed with a structured ``AssistantError``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence

ASSISTANT_CONTRACT_VERSION = 1


class AssistantError(ValueError):
    """A structured, safe-to-serialize assistant error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
            "retryable": self.retryable,
        }


class ScopeKind(StrEnum):
    WORKSPACE = "workspace"
    SEMESTER = "semester"
    COURSE = "course"
    SOURCE = "source"


class PermissionClass(StrEnum):
    READ_LOCAL = "read_local"
    READ_EXTERNAL = "read_external"
    WRITE_LOCAL = "write_local"
    STRUCTURAL = "structural"
    EXTERNAL = "external"
    PROHIBITED = "prohibited"


class SideEffect(StrEnum):
    NONE = "none"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXTERNAL = "external"


class Disclosure(StrEnum):
    LOCAL_ONLY = "local_only"
    HOSTED_MODEL_ELIGIBLE = "hosted_model_eligible"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    CONTEXT_SELECTED = "context_selected"
    TOOL_STARTED = "tool_started"
    TOOL_RESULT = "tool_result"
    PERMISSION_REQUIRED = "permission_required"
    ERROR = "error"
    FINAL = "final"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Scope:
    kind: ScopeKind | str = ScopeKind.WORKSPACE
    semester: str | None = None
    course_id: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        try:
            kind = ScopeKind(self.kind)
        except ValueError as exc:
            raise AssistantError(
                "scope.kind must be workspace, semester, course, or source",
                code="invalid_scope",
            ) from exc
        object.__setattr__(self, "kind", kind)
        if kind is ScopeKind.SEMESTER and not self.semester:
            raise AssistantError("semester scope requires a semester", code="invalid_scope")
        if kind is ScopeKind.COURSE and not (self.semester and self.course_id):
            raise AssistantError("course scope requires a semester and course_id", code="invalid_scope")
        if kind is ScopeKind.SOURCE and not (self.semester and self.source_id):
            raise AssistantError("source scope requires a semester and source_id", code="invalid_scope")
        if kind is ScopeKind.WORKSPACE and any((self.semester, self.course_id, self.source_id)):
            raise AssistantError("workspace scope cannot include narrower identifiers", code="invalid_scope")

    def as_dict(self) -> dict[str, str]:
        value = {"kind": self.kind.value}
        if self.semester:
            value["semester"] = self.semester
        if self.course_id:
            value["course_id"] = self.course_id
        if self.source_id:
            value["source_id"] = self.source_id
        return value


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    version: int
    description: str
    input_schema: dict[str, Any]
    permission: PermissionClass
    side_effect: SideEffect
    disclosure: Disclosure
    requires_approval: bool = False
    idempotent: bool = True
    previewable: bool = False
    verifiable: bool = False

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise AssistantError("tool name is required", code="invalid_tool")
        if not isinstance(self.version, int) or self.version < 1:
            raise AssistantError("tool version must be a positive integer", code="invalid_tool")
        if not isinstance(self.input_schema, dict) or self.input_schema.get("type") != "object":
            raise AssistantError("tool input schema must be an object schema", code="invalid_tool")
        for key, enum_type in (
            ("permission", PermissionClass),
            ("side_effect", SideEffect),
            ("disclosure", Disclosure),
        ):
            value = getattr(self, key)
            try:
                object.__setattr__(self, key, enum_type(value))
            except ValueError as exc:
                raise AssistantError(f"tool {key} is invalid", code="invalid_tool") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_schema,
            "permission": self.permission.value,
            "side_effect": self.side_effect.value,
            "disclosure": self.disclosure.value,
            "requires_approval": self.requires_approval,
            "idempotent": self.idempotent,
            "previewable": self.previewable,
            "verifiable": self.verifiable,
        }


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    tool: str
    data: Any
    scope: Scope | None = None
    citations: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "data": self.data,
            "scope": self.scope.as_dict() if self.scope else None,
            "citations": list(self.citations),
            "warnings": list(self.warnings),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    sequence: int
    event_type: EventType | str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "event_type", EventType(self.event_type))
        except ValueError as exc:
            raise AssistantError(f"unsupported run event: {self.event_type}", code="invalid_event") from exc
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise AssistantError("event sequence must be a non-negative integer", code="invalid_event")

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "data": self.data,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RunRequest:
    messages: tuple[dict[str, str], ...]
    scope: Scope
    max_iterations: int = 8
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.messages:
            raise AssistantError("a run requires at least one message", code="invalid_run")
        if not 1 <= self.max_iterations <= 32:
            raise AssistantError("max_iterations must be between 1 and 32", code="invalid_run")
        if not 1 <= self.timeout_seconds <= 900:
            raise AssistantError("timeout_seconds must be between 1 and 900", code="invalid_run")
        for message in self.messages:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                raise AssistantError("messages must contain user or assistant roles", code="invalid_run")
            if not isinstance(message.get("content"), str):
                raise AssistantError("message content must be text", code="invalid_run")


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    message: str = ""
    events: tuple[RunEvent, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    error: AssistantError | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": ASSISTANT_CONTRACT_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "message": self.message,
            "events": [event.as_dict() for event in self.events],
            "tool_results": [result.as_dict() for result in self.tool_results],
            "error": self.error.to_dict() if self.error else None,
        }


def validate_json_schema(value: Any, schema: Mapping[str, Any], *, path: str = "$") -> None:
    """Validate the small JSON Schema subset used by Academia tool contracts."""

    expected = schema.get("type")
    if expected is not None:
        if expected == "object":
            if not isinstance(value, dict):
                raise AssistantError(f"{path} must be an object", code="invalid_arguments")
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            for name in required:
                if name not in value:
                    raise AssistantError(f"{path}.{name} is required", code="invalid_arguments")
            if schema.get("additionalProperties") is False:
                unknown = sorted(set(value) - set(properties))
                if unknown:
                    raise AssistantError(f"{path} contains unsupported field: {unknown[0]}", code="invalid_arguments")
            for name, child in properties.items():
                if name in value:
                    validate_json_schema(value[name], child, path=f"{path}.{name}")
        elif expected == "array":
            if not isinstance(value, list):
                raise AssistantError(f"{path} must be an array", code="invalid_arguments")
            items = schema.get("items")
            if isinstance(items, dict):
                for index, item in enumerate(value):
                    validate_json_schema(item, items, path=f"{path}[{index}]")
        elif expected == "string":
            if not isinstance(value, str):
                raise AssistantError(f"{path} must be a string", code="invalid_arguments")
            if "maxLength" in schema and len(value) > int(schema["maxLength"]):
                raise AssistantError(f"{path} is too long", code="invalid_arguments")
            if "minLength" in schema and len(value) < int(schema["minLength"]):
                raise AssistantError(f"{path} is too short", code="invalid_arguments")
        elif expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise AssistantError(f"{path} must be an integer", code="invalid_arguments")
        elif expected == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise AssistantError(f"{path} must be a number", code="invalid_arguments")
        elif expected == "boolean":
            if not isinstance(value, bool):
                raise AssistantError(f"{path} must be a boolean", code="invalid_arguments")
        elif expected == "null":
            if value is not None:
                raise AssistantError(f"{path} must be null", code="invalid_arguments")
        else:
            raise AssistantError(f"{path} uses an unsupported schema type", code="invalid_tool")

    if "enum" in schema and value not in schema["enum"]:
        raise AssistantError(f"{path} must be one of {schema['enum']}", code="invalid_arguments")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        raise AssistantError(f"{path} must be at least {schema['minimum']}", code="invalid_arguments")
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        raise AssistantError(f"{path} must be at most {schema['maximum']}", code="invalid_arguments")


def validate_tool_call(descriptor: ToolDescriptor, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise AssistantError("tool arguments must be an object", code="invalid_arguments")
    validate_json_schema(arguments, descriptor.input_schema)
    return dict(arguments)
