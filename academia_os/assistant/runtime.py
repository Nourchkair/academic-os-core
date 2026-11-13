"""Deterministic, read-only first-party assistant runtime.

Phase 2 keeps model/provider access behind ``ProviderAdapter``.  The runtime
validates every proposed tool call through the same registry and policy used by
the CLI and MCP surfaces.  It has no write tools.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable
from uuid import uuid4

from .contracts import AssistantError, EventType, RunEvent, RunRequest, RunResult, Scope, ScopeKind, ToolDescriptor, ToolGrant, ToolResult
from .policy import PolicyDenied, validate_scope
from .providers import CancelToken, ProviderAdapter, ProviderRequest, ProviderResponse, ProviderToolCall
from .registry import WRITE_TOOLS, descriptors, invoke_granted
from .tools.read import ReadContext

_COURSE_TOOL_NAMES = {
    "course.get",
    "task.list",
    "library.list",
    "library.get",
    "library.search_passages",
    "study.overview",
    "study.exam_scope",
    "context.get",
}
_SOURCE_TOOL_NAMES = {"library.get"}
_MAX_TOOL_MESSAGE_CHARS = 60_000


def tools_for_scope(scope: Scope, grants: ToolGrant | None = None) -> list[dict[str, Any]]:
    if scope.kind is ScopeKind.COURSE:
        allowed = _COURSE_TOOL_NAMES
    elif scope.kind is ScopeKind.SOURCE:
        allowed = _SOURCE_TOOL_NAMES
    else:
        allowed = {tool["name"] for tool in descriptors()}
    tools = [tool for tool in descriptors() if tool["name"] in allowed]
    if grants is not None and scope.kind is not ScopeKind.SOURCE:
        tools.extend([
            spec.descriptor.as_dict()
            for name, spec in WRITE_TOOLS.items()
            if grants.allows(name)
        ])
    return tools


def _tool_content(result: dict[str, Any]) -> str:
    content = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if len(content) <= _MAX_TOOL_MESSAGE_CHARS:
        return content
    return content[:_MAX_TOOL_MESSAGE_CHARS] + "\n[Tool result truncated by the runtime.]"


class RunController:
    def __init__(self, context: ReadContext, provider: ProviderAdapter) -> None:
        self.context = context
        self.provider = provider

    def run(
        self,
        request: RunRequest,
        *,
        cancel: CancelToken | None = None,
        grants: ToolGrant | None = None,
        confirm: Callable[[ToolDescriptor, dict[str, Any]], bool] | None = None,
        on_event: Callable[[RunEvent], None] | None = None,
    ) -> RunResult:
        run_id = str(uuid4())
        events: list[RunEvent] = []
        tool_results: list[ToolResult] = []
        messages: list[dict[str, Any]] = [dict(message) for message in request.messages]
        deadline = time.monotonic() + request.timeout_seconds

        def emit(event_type: EventType, data: dict[str, Any] | None = None) -> None:
            event = RunEvent(
                run_id=run_id,
                sequence=len(events),
                event_type=event_type,
                data=data or {},
            )
            events.append(event)
            if on_event is not None:
                on_event(event)

        try:
            validate_scope(request.scope, self.context.policy)
        except PolicyDenied as exc:
            error = AssistantError(str(exc), code=exc.code)
            emit(EventType.ERROR, {"code": error.code, "message": str(error)})
            return RunResult(run_id=run_id, status="error", events=tuple(events), error=error)

        tools = tools_for_scope(request.scope, grants)
        emit(EventType.RUN_STARTED, {
            "provider": self.provider.id,
            "scope": request.scope.as_dict(),
            "tool_count": len(tools),
            "granted_tools": sorted(grants.tools) if grants is not None else [],
        })

        for _iteration in range(request.max_iterations):
            if cancel is not None and cancel.cancelled:
                emit(EventType.CANCELLED, {"reason": "cancelled by client"})
                return RunResult(run_id=run_id, status="cancelled", events=tuple(events), tool_results=tuple(tool_results))
            if time.monotonic() >= deadline:
                error = AssistantError("assistant run timed out", code="run_timeout", retryable=True)
                emit(EventType.ERROR, {"code": error.code, "message": str(error)})
                return RunResult(run_id=run_id, status="error", events=tuple(events), tool_results=tuple(tool_results), error=error)

            try:
                response: ProviderResponse = self.provider.complete(
                    ProviderRequest(messages=tuple(messages), tools=tuple(tools), context=request.context),
                    cancel=cancel,
                )
            except Exception as exc:
                error = AssistantError(str(exc), code="provider_error", retryable=True)
                emit(EventType.ERROR, {"code": error.code, "message": str(error)})
                return RunResult(run_id=run_id, status="error", events=tuple(events), tool_results=tuple(tool_results), error=error)

            if response.tool_calls:
                calls = tuple(
                    call if call.call_id else ProviderToolCall(call.name, call.arguments, f"call-{_iteration}-{index}")
                    for index, call in enumerate(response.tool_calls)
                )
                messages.append({
                    "role": "assistant",
                    "content": response.text or "",
                    "tool_calls": [
                        {"id": call.call_id, "name": call.name, "arguments": dict(call.arguments)}
                        for call in calls
                    ],
                })
                for call in calls:
                    emit(EventType.TOOL_STARTED, {"name": call.name, "call_id": call.call_id})
                    try:
                        result = invoke_granted(
                            call.name,
                            call.arguments,
                            self.context,
                            grants=grants,
                            parent_scope=request.scope,
                            confirm=confirm,
                        )
                    except AssistantError as exc:
                        payload = {"error": exc.to_dict()}
                        emit(EventType.TOOL_RESULT, {
                            "name": call.name,
                            "call_id": call.call_id,
                            "ok": False,
                            "code": exc.code,
                        })
                    else:
                        payload = result.as_dict()
                        tool_results.append(result)
                        event_data: dict[str, Any] = {
                            "name": call.name,
                            "call_id": call.call_id,
                            "ok": True,
                            "truncated": result.truncated,
                            "citation_count": len(result.citations),
                        }
                        if call.name in WRITE_TOOLS:
                            event_data["data"] = result.data
                        emit(EventType.TOOL_RESULT, event_data)
                    messages.append({
                        "role": "tool",
                        "name": call.name,
                        "tool_call_id": call.call_id,
                        "content": _tool_content(payload),
                    })
                continue

            final = response.text.strip()
            if not final:
                error = AssistantError("provider returned neither text nor tool calls", code="invalid_provider_response")
                emit(EventType.ERROR, {"code": error.code, "message": str(error)})
                return RunResult(run_id=run_id, status="error", events=tuple(events), tool_results=tuple(tool_results), error=error)
            emit(EventType.FINAL, {"message": final})
            return RunResult(
                run_id=run_id,
                status="completed",
                message=final,
                events=tuple(events),
                tool_results=tuple(tool_results),
            )

        error = AssistantError("assistant exceeded the maximum number of tool iterations", code="max_iterations", retryable=True)
        emit(EventType.ERROR, {"code": error.code, "message": str(error)})
        return RunResult(run_id=run_id, status="error", events=tuple(events), tool_results=tuple(tool_results), error=error)
