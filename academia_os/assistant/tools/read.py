"""Read-only academic tools exposed to the first-party assistant.

Every function is a thin composition over existing core services.  None of
them writes academic state.  The registry is responsible for schema validation
and policy authorization before a handler is called.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...agent import build_agent_attention, build_agent_changes, build_agent_context
from ...config import validate_config
from ...file_preview import FilePreviewError, preview_file
from ...library import filter_material, list_material
from ...source_identity import SourceIdentityError, identity, validate_source_id
from ...study import StudyService
from ...workspace import build_workspace_snapshot
from ..contracts import AssistantError, Scope, ToolResult
from ..policy import PolicyContext, policy_context, resolve_course


@dataclass(frozen=True)
class ReadContext:
    config: dict[str, Any]
    snapshot: dict[str, Any]
    policy: PolicyContext

    @classmethod
    def create(cls, config: dict[str, Any], *, semester: str | None = None, hosted_model_allowed: bool = False) -> "ReadContext":
        normalized = validate_config(config)
        snapshot = build_workspace_snapshot(
            normalized,
            persist=False,
            semester_override=semester,
            include_material=False,
            count_inbox_files=False,
        )
        return cls(
            config=normalized,
            snapshot=snapshot,
            policy=policy_context(snapshot, hosted_model_allowed=hosted_model_allowed),
        )

    @property
    def root(self) -> Path:
        return self.policy.root

    @property
    def semester(self) -> str:
        return self.policy.semester

    def materials(self) -> list[dict[str, Any]]:
        return list_material(self.root, self.semester)


def _tool(tool: str, data: Any, *, scope: Scope | None = None, warnings: list[str] | None = None, truncated: bool = False) -> ToolResult:
    return ToolResult(
        tool=tool,
        data=data,
        scope=scope,
        warnings=tuple(warnings or ()),
        truncated=truncated,
    )


def workspace_summary(context: ReadContext) -> ToolResult:
    snapshot = build_workspace_snapshot(
        context.config,
        persist=False,
        semester_override=context.semester,
        include_material=True,
        count_inbox_files=True,
    )
    data = {
        "semester": snapshot["semester"],
        "available_semesters": snapshot.get("available_semesters", []),
        "timezone": snapshot.get("timezone"),
        "course_count": len(snapshot.get("courses", [])),
        "material_count": snapshot.get("material_count", 0),
        "inbox_count": snapshot.get("inbox_count", 0),
        "review_count": snapshot.get("review_count", 0),
        "workspace_exists": snapshot.get("workspace_exists", False),
        "workspace_recognized": snapshot.get("workspace_recognized", False),
    }
    return _tool("workspace.summary", data)


def list_courses(context: ReadContext) -> ToolResult:
    courses = [
        {
            "id": str(course.get("id")),
            "code": course.get("code"),
            "name": course.get("name"),
            "material_count": course.get("material_count", 0),
            "inbox_count": course.get("inbox_count", 0),
            "review_required": course.get("review_required", False),
        }
        for course in context.snapshot.get("courses", [])
    ]
    return _tool("course.list", courses)


def get_course(context: ReadContext, identifier: str) -> ToolResult:
    course = resolve_course(context.policy, identifier)
    data = {
        "id": str(course.get("id")),
        "code": course.get("code"),
        "name": course.get("name"),
        "material_count": course.get("material_count", 0),
        "inbox_count": course.get("inbox_count", 0),
        "review_required": course.get("review_required", False),
        "status_file": course.get("status_file"),
    }
    return _tool("course.get", data, scope=Scope(kind="course", semester=context.semester, course_id=str(course["id"])))


def list_tasks(context: ReadContext, *, course: str | None = None, include_completed: bool = False) -> ToolResult:
    course_id = str(resolve_course(context.policy, course)["id"]) if course else None
    tasks = [dict(task) for task in context.snapshot.get("tasks", [])]
    if course_id:
        tasks = [task for task in tasks if task.get("course") == course_id]
    if not include_completed:
        tasks = [task for task in tasks if not task.get("completed")]
    tasks.sort(key=lambda task: (str(task.get("due_date") or "9999-99-99"), str(task.get("due_time") or ""), str(task.get("title", ""))))
    return _tool("task.list", tasks, scope=Scope(kind="course", semester=context.semester, course_id=course_id) if course_id else None)


def list_library(
    context: ReadContext,
    *,
    course: str | None = None,
    category: str = "all",
    location: str = "all",
    processing_status: str = "all",
    query: str = "",
    limit: int = 100,
) -> ToolResult:
    course_id = str(resolve_course(context.policy, course)["id"]) if course else None
    materials = filter_material(
        context.materials(),
        category=category,
        location=location,
        processing_status=processing_status,
        course_id=course_id,
        query=query,
    )
    truncated = len(materials) > limit
    data = [{key: item.get(key) for key in (
        "id", "name", "relative_path", "semester", "course_id", "category", "intake_status",
        "extension", "size", "modified_at", "provenance", "source_type", "processing_status", "extraction_status",
    )} for item in materials[:limit]]
    return _tool(
        "library.list",
        data,
        scope=Scope(kind="course", semester=context.semester, course_id=course_id) if course_id else None,
        truncated=truncated,
    )


def get_library_item(context: ReadContext, item_id: str) -> ToolResult:
    try:
        path = validate_source_id(context.root, item_id, semester=context.semester)
    except SourceIdentityError as exc:
        raise AssistantError(str(exc), code="unsafe_source") from exc
    course_id = path.relative_to(context.root).parts[1] if len(path.relative_to(context.root).parts) >= 3 else None
    scope = Scope(kind="course", semester=context.semester, course_id=course_id) if course_id else None
    try:
        preview = preview_file(path, workspace_root=context.root, semester=context.semester)
    except FilePreviewError as exc:
        raise AssistantError(str(exc), code="preview_failed") from exc
    try:
        source_identity = identity(path, root=context.root)
    except (OSError, SourceIdentityError) as exc:
        raise AssistantError(str(exc), code="source_identity_failed") from exc
    preview = {**preview, "identity": source_identity}
    return _tool("library.get", preview, scope=scope)


def search_passages(
    context: ReadContext,
    *,
    course: str,
    query: str,
    source_ids: list[str] | None = None,
    pages: str | None = None,
    limit: int = 12,
    deep: bool = False,
) -> ToolResult:
    course_id = str(resolve_course(context.policy, course)["id"])
    service = StudyService(context.root, context.semester, course_id)
    try:
        result = service.context(
            source_ids=source_ids or [],
            query=query,
            pages=pages,
            limit=limit,
            deep=deep,
        )
    except (OSError, ValueError) as exc:
        raise AssistantError(str(exc), code="retrieval_failed") from exc
    scope = Scope(kind="course", semester=context.semester, course_id=course_id)
    warnings = list(result.get("warnings") or [])
    citations = tuple(
        {
            "id": chunk.get("id"),
            "source_id": chunk.get("source_id"),
            "source_name": chunk.get("source_name"),
            "locator": chunk.get("locator"),
            "sha256": chunk.get("sha256"),
            "ocr": chunk.get("ocr", False),
        }
        for chunk in result.get("chunks", [])
        if isinstance(chunk, dict)
    )
    return ToolResult(
        tool="library.search_passages",
        data=result,
        scope=scope,
        citations=citations,
        warnings=tuple(warnings),
        truncated=bool(result.get("truncated")),
    )


def study_overview(context: ReadContext, *, course: str) -> ToolResult:
    course_id = str(resolve_course(context.policy, course)["id"])
    try:
        data = StudyService(context.root, context.semester, course_id).overview()
    except (OSError, ValueError) as exc:
        raise AssistantError(str(exc), code="study_unavailable") from exc
    return _tool("study.overview", data, scope=Scope(kind="course", semester=context.semester, course_id=course_id))


def study_exam_scope(context: ReadContext, *, course: str, exam_id: str | None = None) -> ToolResult:
    course_id = str(resolve_course(context.policy, course)["id"])
    service = StudyService(context.root, context.semester, course_id)
    try:
        if exam_id:
            data = service.exam_context(exam_id)
        else:
            data = service.overview().get("exams", [])
    except (OSError, ValueError, KeyError) as exc:
        raise AssistantError(str(exc), code="study_unavailable") from exc
    scope = Scope(kind="course", semester=context.semester, course_id=course_id)
    return _tool("study.exam_scope", data, scope=scope)


def review_attention(context: ReadContext, *, detail: str = "standard") -> ToolResult:
    try:
        data = build_agent_attention(context.config, context.snapshot, detail=detail)
    except (OSError, ValueError, KeyError) as exc:
        raise AssistantError(str(exc), code="attention_unavailable") from exc
    return _tool("review.attention", data)


def activity_changes(context: ReadContext, *, since: str | None = None, limit: int = 100) -> ToolResult:
    try:
        data = build_agent_changes(context.config, since=since, limit=limit)
    except (OSError, ValueError) as exc:
        raise AssistantError(str(exc), code="activity_unavailable") from exc
    return _tool("activity.changes", data)


def agent_context(context: ReadContext, *, scope: str = "workspace", course: str | None = None, detail: str = "compact") -> ToolResult:
    try:
        data = build_agent_context(
            context.config,
            context.snapshot,
            scope=scope,
            detail=detail,
            course_id=course,
        )
    except (OSError, ValueError, KeyError) as exc:
        raise AssistantError(str(exc), code="context_unavailable") from exc
    return _tool("context.get", data)
