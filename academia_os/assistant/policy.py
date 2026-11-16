"""Central authorization for assistant tools.

The UI, MCP host, and model never decide whether a tool is allowed.  Every
invocation is validated here against a workspace-derived policy context.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .contracts import AssistantError, Disclosure, PermissionClass, Scope, ScopeKind, ToolDescriptor
from ..course_identity import resolve_course_identifier
from ..source_identity import SourceIdentityError, validate_source_id


class PolicyDenied(AssistantError):
    def __init__(self, message: str, *, reason: str = "policy_denied") -> None:
        super().__init__(message, code=reason)


@dataclass(frozen=True)
class PolicyContext:
    root: Path
    semester: str
    courses: tuple[dict[str, Any], ...]
    available_semesters: tuple[str, ...]
    hosted_model_allowed: bool = False

    @property
    def course_ids(self) -> frozenset[str]:
        return frozenset(str(course["id"]) for course in self.courses)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    requires_approval: bool = False
    disclosure: Disclosure = Disclosure.LOCAL_ONLY
    hosted_disclosure_allowed: bool = False

    def ensure(self) -> None:
        if not self.allowed:
            raise PolicyDenied(self.reason)


def policy_context(snapshot: Mapping[str, Any], *, hosted_model_allowed: bool = False) -> PolicyContext:
    root_value = snapshot.get("academic_root")
    semester = snapshot.get("semester")
    if not isinstance(root_value, str) or not root_value:
        raise PolicyDenied("workspace root is unavailable", reason="workspace_unavailable")
    if not isinstance(semester, str) or not semester:
        raise PolicyDenied("workspace semester is unavailable", reason="workspace_unavailable")
    courses = tuple(dict(course) for course in snapshot.get("courses", []) if isinstance(course, Mapping) and course.get("id"))
    available = tuple(str(value) for value in snapshot.get("available_semesters", []) if isinstance(value, str))
    return PolicyContext(
        root=Path(root_value).expanduser().resolve(),
        semester=semester,
        courses=courses,
        available_semesters=available,
        hosted_model_allowed=hosted_model_allowed,
    )


def resolve_course(policy: PolicyContext, identifier: str) -> dict[str, Any]:
    try:
        course = resolve_course_identifier(policy.courses, identifier)
    except (KeyError, ValueError) as exc:
        raise PolicyDenied(str(exc), reason="unknown_course") from exc
    if str(course["id"]) not in policy.course_ids:
        raise PolicyDenied("course is outside the selected workspace", reason="unknown_course")
    return dict(course)


def validate_scope(scope: Scope, policy: PolicyContext) -> None:
    if scope.kind is ScopeKind.WORKSPACE:
        return
    if scope.kind is ScopeKind.SEMESTER:
        if scope.semester != policy.semester and scope.semester not in policy.available_semesters:
            raise PolicyDenied("semester is not recognized in this workspace", reason="unknown_semester")
        return
    if scope.kind is ScopeKind.COURSE:
        course = resolve_course(policy, str(scope.course_id))
        if scope.semester != policy.semester:
            raise PolicyDenied("course scope must use the selected semester", reason="unknown_semester")
        if str(course["id"]) != scope.course_id:
            raise PolicyDenied("course identifier did not resolve to the requested course", reason="unknown_course")
        return
    if scope.kind is ScopeKind.SOURCE:
        semester = str(scope.semester)
        if semester != policy.semester and semester not in policy.available_semesters:
            raise PolicyDenied("semester is not recognized in this workspace", reason="unknown_semester")
        try:
            path = validate_source_id(policy.root, str(scope.source_id), semester=semester)
        except SourceIdentityError as exc:
            raise PolicyDenied(str(exc), reason="unsafe_source") from exc
        relative = path.relative_to(policy.root)
        if len(relative.parts) < 2:
            raise PolicyDenied("source must belong to a recognized semester", reason="unsafe_source")
        if scope.course_id and (len(relative.parts) < 3 or relative.parts[1] != scope.course_id):
            raise PolicyDenied("source does not belong to the requested course", reason="cross_course_source")
        return
    raise PolicyDenied("unsupported scope", reason="invalid_scope")


def authorize_tool(
    descriptor: ToolDescriptor,
    scope: Scope,
    policy: PolicyContext,
    *,
    arguments: Mapping[str, Any] | None = None,
) -> PolicyDecision:
    del arguments  # Reserved for future per-tool argument policy.
    if descriptor.permission is PermissionClass.PROHIBITED:
        return PolicyDecision(False, "this tool is prohibited by Academia policy")
    if descriptor.permission in {PermissionClass.WRITE_LOCAL, PermissionClass.STRUCTURAL, PermissionClass.EXTERNAL}:
        return PolicyDecision(False, "write and external tools require the approval workflow", requires_approval=True)
    if descriptor.requires_approval:
        return PolicyDecision(False, "this tool requires explicit approval", requires_approval=True)
    try:
        validate_scope(scope, policy)
    except PolicyDenied as exc:
        return PolicyDecision(False, exc.reason)
    return PolicyDecision(
        True,
        "allowed",
        disclosure=descriptor.disclosure,
        hosted_disclosure_allowed=policy.hosted_model_allowed,
    )


def ensure_scope_in_workspace(scope: Scope, policy: PolicyContext) -> None:
    """Convenience wrapper for callers that want a raised error."""

    validate_scope(scope, policy)


def scope_within(child: Scope, parent: Scope) -> bool:
    """Return whether one tool call stays inside the run's selected scope."""
    if parent.kind is ScopeKind.WORKSPACE:
        return True
    if parent.kind is ScopeKind.SEMESTER:
        if child.kind in {ScopeKind.WORKSPACE, ScopeKind.SEMESTER}:
            return child.semester in {None, parent.semester}
        return child.semester == parent.semester
    if parent.kind is ScopeKind.COURSE:
        return child.kind in {ScopeKind.COURSE, ScopeKind.SOURCE} and child.course_id == parent.course_id
    if parent.kind is ScopeKind.SOURCE:
        return child.kind is ScopeKind.SOURCE and child.source_id == parent.source_id
    return False


def course_scope(policy: PolicyContext, course_id: str) -> Scope:
    course = resolve_course(policy, course_id)
    return Scope(kind=ScopeKind.COURSE, semester=policy.semester, course_id=str(course["id"]))


def source_scope(policy: PolicyContext, source_id: str, *, course_id: str | None = None) -> Scope:
    value = Scope(
        kind=ScopeKind.SOURCE,
        semester=policy.semester,
        course_id=course_id,
        source_id=source_id,
    )
    validate_scope(value, policy)
    return value


def source_belongs_to_course(source_id: str, course_id: str) -> bool:
    relative = PurePosixPath(source_id)
    return len(relative.parts) >= 3 and relative.parts[1] == course_id


def filter_courses_for_scope(policy: PolicyContext, scope: Scope) -> tuple[dict[str, Any], ...]:
    if scope.kind is ScopeKind.WORKSPACE:
        return policy.courses
    if scope.kind is ScopeKind.SEMESTER:
        return policy.courses if scope.semester == policy.semester else ()
    if scope.kind is ScopeKind.COURSE:
        return tuple(course for course in policy.courses if str(course["id"]) == scope.course_id)
    if scope.kind is ScopeKind.SOURCE:
        relative = PurePosixPath(str(scope.source_id))
        if len(relative.parts) >= 3:
            return tuple(course for course in policy.courses if str(course["id"]) == relative.parts[1])
    return ()


def course_ids_in_scope(policy: PolicyContext, scope: Scope) -> set[str]:
    return {str(course["id"]) for course in filter_courses_for_scope(policy, scope)}


def known_course_ids(policy: PolicyContext) -> set[str]:
    return set(policy.course_ids)


def visible_courses(policy: PolicyContext, course_ids: Iterable[str]) -> list[dict[str, Any]]:
    allowed = set(course_ids)
    return [dict(course) for course in policy.courses if str(course["id"]) in allowed]
