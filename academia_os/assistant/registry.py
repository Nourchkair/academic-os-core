"""Registry of assistant tools and their policy descriptors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .contracts import (
    AssistantError,
    Disclosure,
    PermissionClass,
    Scope,
    SideEffect,
    ToolDescriptor,
    ToolResult,
    validate_tool_call,
)
from .policy import PolicyContext, PolicyDenied, authorize_tool, resolve_course, scope_within
from .tools import read
from ..source_identity import SourceIdentityError, validate_source_id


@dataclass(frozen=True)
class ToolSpec:
    descriptor: ToolDescriptor
    handler: Callable[[read.ReadContext, dict[str, Any]], ToolResult]


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string(description: str, *, max_length: int = 500) -> dict[str, Any]:
    return {"type": "string", "description": description, "maxLength": max_length}


def _integer(description: str, *, minimum: int = 1, maximum: int = 500) -> dict[str, Any]:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def _boolean(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def _read(
    name: str,
    description: str,
    schema: dict[str, Any],
    handler: Callable[[read.ReadContext, dict[str, Any]], ToolResult],
    *,
    disclosure: Disclosure = Disclosure.LOCAL_ONLY,
) -> ToolSpec:
    return ToolSpec(
        descriptor=ToolDescriptor(
            name=name,
            version=1,
            description=description,
            input_schema=schema,
            permission=PermissionClass.READ_LOCAL,
            side_effect=SideEffect.NONE,
            disclosure=disclosure,
            requires_approval=False,
            idempotent=True,
            previewable=False,
            verifiable=True,
        ),
        handler=handler,
    )


READ_TOOLS: dict[str, ToolSpec] = {
    spec.descriptor.name: spec
    for spec in [
        _read(
            "workspace.summary",
            "Read a bounded summary of the configured academic workspace.",
            _object_schema({}),
            lambda context, arguments: read.workspace_summary(context),
        ),
        _read(
            "course.list",
            "List recognized courses in the selected semester.",
            _object_schema({}),
            lambda context, arguments: read.list_courses(context),
        ),
        _read(
            "course.get",
            "Read one recognized course by exact ID, code, or name.",
            _object_schema({"course": _string("Exact course ID, code, or name")}, ["course"]),
            lambda context, arguments: read.get_course(context, arguments["course"]),
        ),
        _read(
            "task.list",
            "List open academic tasks and recorded deadlines.",
            _object_schema({
                "course": _string("Optional exact course ID, code, or name"),
                "include_completed": _boolean("Include completed tasks"),
            }),
            lambda context, arguments: read.list_tasks(
                context,
                course=arguments.get("course"),
                include_completed=bool(arguments.get("include_completed", False)),
            ),
        ),
        _read(
            "library.list",
            "List bounded Library metadata, never file bodies.",
            _object_schema({
                "course": _string("Optional exact course ID, code, or name"),
                "category": {"type": "string", "enum": ["all", "syllabi", "readings", "lectures", "assessments", "notes", "other"]},
                "location": {"type": "string", "enum": ["all", "inbox", "organized"]},
                "processing_status": {"type": "string", "enum": ["all", "not_processed", "in_progress", "processed", "failed", "untracked"]},
                "query": _string("Optional metadata search text"),
                "limit": _integer("Maximum items to return", maximum=100),
            }),
            lambda context, arguments: read.list_library(
                context,
                course=arguments.get("course"),
                category=arguments.get("category", "all"),
                location=arguments.get("location", "all"),
                processing_status=arguments.get("processing_status", "all"),
                query=arguments.get("query", ""),
                limit=int(arguments.get("limit", 100)),
            ),
        ),
        _read(
            "library.get",
            "Read a bounded preview of one exact Library source by workspace-relative ID.",
            _object_schema({"item_id": _string("Exact workspace-relative Library ID")}, ["item_id"]),
            lambda context, arguments: read.get_library_item(context, arguments["item_id"]),
            disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE,
        ),
        _read(
            "library.search_passages",
            "Search the full text of selected course sources and return page-addressed passages with citations.",
            _object_schema({
                "course": _string("Exact course ID, code, or name"),
                "query": _string("Topic or question to retrieve passages for", max_length=2000),
                "source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 300},
                "pages": _string("Optional 1-based PDF page or range", max_length=40),
                "limit": _integer("Maximum passages to return", maximum=128),
                "deep": _boolean("Search every extractable page and selected source"),
            }, ["course", "query"]),
            lambda context, arguments: read.search_passages(
                context,
                course=arguments["course"],
                query=arguments["query"],
                source_ids=arguments.get("source_ids"),
                pages=arguments.get("pages"),
                limit=int(arguments.get("limit", 12)),
                deep=bool(arguments.get("deep", False)),
            ),
            disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE,
        ),
        _read(
            "study.overview",
            "Read saved Study sets, sessions, topics, due reviews, annotations, and exam scope without answer keys.",
            _object_schema({"course": _string("Exact course ID, code, or name")}, ["course"]),
            lambda context, arguments: read.study_overview(context, course=arguments["course"]),
            disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE,
        ),
        _read(
            "study.exam_scope",
            "Read recorded exam scope and coverage, or one exact exam record.",
            _object_schema({
                "course": _string("Exact course ID, code, or name"),
                "exam_id": _string("Optional exact exam record ID"),
            }, ["course"]),
            lambda context, arguments: read.study_exam_scope(
                context,
                course=arguments["course"],
                exam_id=arguments.get("exam_id"),
            ),
            disclosure=Disclosure.HOSTED_MODEL_ELIGIBLE,
        ),
        _read(
            "review.attention",
            "Read unresolved Review decisions and retryable local issues.",
            _object_schema({"detail": {"type": "string", "enum": ["compact", "standard", "deep"]}}),
            lambda context, arguments: read.review_attention(context, detail=arguments.get("detail", "standard")),
        ),
        _read(
            "activity.changes",
            "Read append-only Activity changes after an optional cursor.",
            _object_schema({
                "since": _string("Optional Activity ID or ISO timestamp"),
                "limit": _integer("Maximum events to return", maximum=500),
            }),
            lambda context, arguments: read.activity_changes(
                context,
                since=arguments.get("since"),
                limit=int(arguments.get("limit", 100)),
            ),
        ),
        _read(
            "context.get",
            "Read the existing bounded agent context for a workspace, semester, course, or today scope.",
            _object_schema({
                "scope": {"type": "string", "enum": ["workspace", "semester", "course", "today"]},
                "course": _string("Exact course ID, code, or name for course scope"),
                "detail": {"type": "string", "enum": ["compact", "standard", "deep"]},
            }),
            lambda context, arguments: read.agent_context(
                context,
                scope=arguments.get("scope", "workspace"),
                course=arguments.get("course"),
                detail=arguments.get("detail", "compact"),
            ),
        ),
    ]
}


def descriptors() -> list[dict[str, Any]]:
    return [spec.descriptor.as_dict() for spec in READ_TOOLS.values()]


def descriptor(name: str) -> ToolDescriptor:
    try:
        return READ_TOOLS[name].descriptor
    except KeyError as exc:
        raise AssistantError(f"unknown assistant tool: {name}", code="unknown_tool") from exc


def _scope_for(arguments: Mapping[str, Any], context: read.ReadContext) -> Scope:
    if "item_id" in arguments:
        try:
            path = validate_source_id(context.root, str(arguments["item_id"]), semester=context.semester)
        except SourceIdentityError as exc:
            raise AssistantError(str(exc), code="unsafe_source") from exc
        relative = path.relative_to(context.root)
        course_id = relative.parts[1] if len(relative.parts) >= 3 else None
        return Scope(kind="source", semester=context.semester, course_id=course_id, source_id=str(arguments["item_id"]))
    if "course" in arguments and arguments["course"]:
        course = resolve_course(context.policy, str(arguments["course"]))
        return Scope(kind="course", semester=context.semester, course_id=str(course["id"]))
    return Scope(kind="workspace")


def invoke(
    name: str,
    arguments: Any,
    context: read.ReadContext,
    *,
    policy: PolicyContext | None = None,
    parent_scope: Scope | None = None,
) -> ToolResult:
    spec = READ_TOOLS.get(name)
    if spec is None:
        raise AssistantError(f"unknown assistant tool: {name}", code="unknown_tool")
    values = validate_tool_call(spec.descriptor, arguments)
    scope = _scope_for(values, context)
    if parent_scope is not None and not scope_within(scope, parent_scope):
        raise PolicyDenied("tool call is outside the selected run scope")
    decision = authorize_tool(spec.descriptor, scope, policy or context.policy, arguments=values)
    if not decision.allowed:
        raise PolicyDenied(decision.reason)
    return spec.handler(context, values)
