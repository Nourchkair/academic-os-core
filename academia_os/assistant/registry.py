"""Registry of assistant tools and their policy descriptors."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .contracts import (
    AssistantError,
    Disclosure,
    PermissionClass,
    Scope,
    ScopeKind,
    SideEffect,
    ToolDescriptor,
    ToolGrant,
    ToolResult,
    validate_tool_call,
)
from .policy import PolicyContext, PolicyDenied, authorize_tool, resolve_course, scope_within
from .tools import read
from .tools.write import (
    DOMAIN_CHANGE_DESCRIPTOR,
    IMPORT_PROPOSAL_DESCRIPTOR,
    STUDY_CREATE_DESCRIPTOR,
    TASK_PROPOSAL_DESCRIPTOR,
    create_study_set,
    propose_domain_change,
    propose_import,
    propose_task_change,
)
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


def _propose_import_handler(context: read.ReadContext, arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool="import.propose",
        data=propose_import(
            context,
            source_path=arguments["source_path"],
            target_id=arguments["target_id"],
            source_label=arguments.get("source_label"),
        ),
    )


def _propose_task_handler(context: read.ReadContext, arguments: dict[str, Any]) -> ToolResult:
    optional = {
        key: arguments[key]
        for key in ("task_id", "title", "course", "due_date", "due_time", "source_location", "confidence", "authority")
        if key in arguments
    }
    return ToolResult(
        tool="task.propose",
        data=propose_task_change(
            context,
            action=arguments["action"],
            evidence_source=arguments["evidence_source"],
            evidence_path=arguments["evidence_path"],
            **optional,
        ),
    )


def _propose_domain_handler(context: read.ReadContext, arguments: dict[str, Any]) -> ToolResult:
    optional = {
        key: arguments[key]
        for key in ("source_location", "confidence", "authority")
        if key in arguments
    }
    return ToolResult(
        tool="domain.propose",
        data=propose_domain_change(
            context,
            course=arguments["course"],
            entity_type=arguments["entity_type"],
            entity_id=arguments["entity_id"],
            field=arguments["field"],
            after=arguments["after"],
            evidence_source=arguments["evidence_source"],
            evidence_path=arguments["evidence_path"],
            **optional,
        ),
    )


def _create_study_handler(context: read.ReadContext, arguments: dict[str, Any]) -> ToolResult:
    optional = {
        key: arguments[key]
        for key in ("source_ids", "query", "pages", "limit", "deep")
        if key in arguments
    }
    return ToolResult(
        tool="study.create",
        data=create_study_set(
            context,
            course=arguments["course"],
            payload=arguments["payload"],
            **optional,
        ),
    )


WRITE_TOOLS: dict[str, ToolSpec] = {
    spec.descriptor.name: spec
    for spec in [
        ToolSpec(IMPORT_PROPOSAL_DESCRIPTOR, _propose_import_handler),
        ToolSpec(STUDY_CREATE_DESCRIPTOR, _create_study_handler),
        ToolSpec(DOMAIN_CHANGE_DESCRIPTOR, _propose_domain_handler),
        ToolSpec(TASK_PROPOSAL_DESCRIPTOR, _propose_task_handler),
    ]
}


def write_descriptors() -> list[dict[str, Any]]:
    return [spec.descriptor.as_dict() for spec in WRITE_TOOLS.values()]


def write_spec(name: str) -> ToolSpec:
    try:
        return WRITE_TOOLS[name]
    except KeyError as exc:
        raise AssistantError(f"unknown assistant write tool: {name}", code="unknown_tool") from exc


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


def _validate_write_scope(name: str, values: dict[str, Any], context: read.ReadContext, parent_scope: Scope | None) -> None:
    if parent_scope is None or parent_scope.kind is ScopeKind.WORKSPACE:
        return
    if parent_scope.kind is ScopeKind.SOURCE:
        raise PolicyDenied("write tools are unavailable in source scope", reason="tool_not_granted")
    if parent_scope.kind is ScopeKind.COURSE:
        course_id = str(parent_scope.course_id)
        if name == "import.propose":
            target = str(values.get("target_id") or "")
            if target != f"{parent_scope.semester}/{course_id}/00_INBOX":
                raise PolicyDenied("import target is outside the selected course", reason="scope_denied")
            return
        if name == "task.propose":
            if values.get("action") == "update":
                from ..tasks import TaskStore
                try:
                    task = TaskStore(context.root, context.semester).get(str(values.get("task_id") or ""))
                except (KeyError, ValueError) as exc:
                    raise AssistantError(str(exc), code="unknown_task") from exc
                if task.get("course_id") != course_id:
                    raise PolicyDenied("task is outside the selected course", reason="scope_denied")
            if values.get("course"):
                try:
                    requested = resolve_course(context.policy, str(values["course"]))
                except PolicyDenied:
                    raise
                if str(requested["id"]) != course_id:
                    raise PolicyDenied("course is outside the selected course", reason="scope_denied")
            else:
                values["course"] = course_id
            return
        if name in {"domain.propose", "study.create"}:
            try:
                requested = resolve_course(context.policy, str(values.get("course") or ""))
            except PolicyDenied as exc:
                raise AssistantError(str(exc), code="unknown_course") from exc
            if str(requested["id"]) != course_id:
                raise PolicyDenied("course is outside the selected course", reason="scope_denied")
            return
    if parent_scope.kind is ScopeKind.SEMESTER:
        if name == "import.propose":
            target = str(values.get("target_id") or "")
            if not target.startswith(f"{parent_scope.semester}/"):
                raise PolicyDenied("import target is outside the selected semester", reason="scope_denied")


def invoke_granted(
    name: str,
    arguments: Any,
    context: read.ReadContext,
    *,
    grants: ToolGrant | None,
    parent_scope: Scope | None = None,
    confirm: Callable[[ToolDescriptor, dict[str, Any]], bool] | None = None,
) -> ToolResult:
    """Invoke a read tool or one explicitly granted write/proposal tool."""
    if name in READ_TOOLS:
        return invoke(name, arguments, context, parent_scope=parent_scope)
    spec = WRITE_TOOLS.get(name)
    if spec is None:
        raise AssistantError(f"unknown assistant tool: {name}", code="unknown_tool")
    if grants is None or not grants.allows(name):
        raise AssistantError("this tool was not granted by the host", code="tool_not_granted")
    values = validate_tool_call(spec.descriptor, arguments)
    _validate_write_scope(name, values, context, parent_scope)
    if not spec.descriptor.requires_approval:
        if confirm is None or not confirm(spec.descriptor, dict(values)):
            raise AssistantError("this write requires explicit host confirmation", code="confirmation_required")
    result = spec.handler(context, values)
    if result.scope is None and parent_scope is not None:
        result = ToolResult(
            tool=result.tool,
            data=result.data,
            scope=parent_scope,
            citations=result.citations,
            warnings=result.warnings,
            truncated=result.truncated,
        )
    return result
