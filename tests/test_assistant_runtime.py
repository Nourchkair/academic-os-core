from __future__ import annotations

import hashlib
from pathlib import Path

from academia_os.assistant import (
    CancelToken,
    FakeProvider,
    RunController,
    RunRequest,
    Scope,
)
from academia_os.assistant.runtime import tools_for_scope
from tests.test_agent_interface import prepared_workspace

SOURCE = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"
COURSE = "POL 2103 - Politics"


def make_context(tmp_path: Path):
    config, root, _ = prepared_workspace(tmp_path)
    from academia_os.assistant import ReadContext

    return ReadContext.create(config, hosted_model_allowed=True), root


def course_scope() -> Scope:
    return Scope(kind="course", semester="Fall 2026", course_id=COURSE)


def source_scope() -> Scope:
    return Scope(kind="source", semester="Fall 2026", course_id=COURSE, source_id=SOURCE)


def user_request(scope: Scope, *, max_iterations: int = 4) -> RunRequest:
    return RunRequest(messages=({"role": "user", "content": "Find the reading about private content."},), scope=scope, max_iterations=max_iterations)


def test_read_only_runtime_completes_a_two_step_retrieval(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([
        {"tool_calls": [{"name": "library.search_passages", "arguments": {"course": COURSE, "query": "Private source content", "limit": 4}}]},
        {"text": "The reading is week-4-reading.md; it says private source content stays out of context."},
    ])

    result = RunController(context, provider).run(user_request(course_scope()))

    assert result.status == "completed"
    assert "week-4-reading.md" in result.message
    assert [event.event_type.value for event in result.events] == [
        "run_started",
        "tool_started",
        "tool_result",
        "final",
    ]
    assert result.tool_results
    assert result.tool_results[0].citations
    assert provider.requests
    assert all(tool["name"] != "workspace.summary" for tool in provider.requests[0].tools)
    assert provider.requests[1].messages[-1]["role"] == "tool"
    assert "chunks" in provider.requests[1].messages[-1]["content"]


def test_course_scope_rejects_unscoped_library_enumeration(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([
        {"tool_calls": [{"name": "library.list", "arguments": {}}]},
        {"text": "I could not use an unscoped Library listing."},
    ])

    result = RunController(context, provider).run(user_request(course_scope()))

    assert result.status == "completed"
    tool_event = next(event for event in result.events if event.event_type.value == "tool_result")
    assert tool_event.data["ok"] is False
    assert tool_event.data["code"] == "policy_denied"


def test_source_scope_allows_only_the_selected_source(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([
        {"tool_calls": [{"name": "library.get", "arguments": {"item_id": SOURCE}}]},
        {"text": "I read the selected source."},
    ])

    result = RunController(context, provider).run(user_request(source_scope()))
    assert result.status == "completed"
    assert result.tool_results[0].data["name"] == "week-4-reading.md"
    assert [tool["name"] for tool in provider.requests[0].tools] == ["library.get"]

    provider = FakeProvider([
        {"tool_calls": [{"name": "library.get", "arguments": {"item_id": "Fall 2026/POL 2103 - Politics/01_COURSE/Course_Status.md"}}]},
        {"text": "I could not read another source."},
    ])
    result = RunController(context, provider).run(user_request(source_scope()))
    tool_event = next(event for event in result.events if event.event_type.value == "tool_result")
    assert tool_event.data["ok"] is False


def test_unknown_tools_and_invalid_arguments_become_tool_errors(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([
        {"tool_calls": [{"name": "not-a-tool", "arguments": {}}]},
        {"tool_calls": [{"name": "course.get", "arguments": {}}]},
        {"text": "I recovered from the tool errors."},
    ])

    result = RunController(context, provider).run(user_request(course_scope()))

    assert result.status == "completed"
    errors = [event for event in result.events if event.event_type.value == "tool_result" and event.data["ok"] is False]
    assert len(errors) == 2
    assert {event.data["code"] for event in errors} == {"unknown_tool", "invalid_arguments"}


def test_max_iterations_and_provider_errors_are_reported(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    loop = [{"tool_calls": [{"name": "course.get", "arguments": {"course": COURSE}}]} for _ in range(3)]
    result = RunController(context, FakeProvider(loop)).run(user_request(course_scope(), max_iterations=2))
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "max_iterations"

    result = RunController(context, FakeProvider([])).run(user_request(course_scope()))
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "provider_error"


def test_cancellation_is_reported_without_calling_the_provider(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([{"text": "should not be requested"}])
    cancel = CancelToken()
    cancel.cancel()

    result = RunController(context, provider).run(user_request(course_scope()), cancel=cancel)

    assert result.status == "cancelled"
    assert provider.requests == []
    assert result.events[-1].event_type.value == "cancelled"


def test_runtime_is_read_only(tmp_path: Path) -> None:
    context, root = make_context(tmp_path)
    source = root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"
    status = root / "Fall 2026" / "POL 2103 - Politics" / "01_COURSE" / "Course_Status.md"
    before = (hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(status.read_bytes()).hexdigest())
    provider = FakeProvider([
        {"tool_calls": [{"name": "library.search_passages", "arguments": {"course": COURSE, "query": "reading"}}]},
        {"text": "Done."},
    ])

    RunController(context, provider).run(user_request(course_scope()))

    after = (hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(status.read_bytes()).hexdigest())
    assert after == before


def test_tools_for_scope_narrows_course_and_source_tools() -> None:
    course_names = {tool["name"] for tool in tools_for_scope(course_scope())}
    assert "library.search_passages" in course_names
    assert "course.list" not in course_names
    assert "review.attention" not in course_names
    assert {tool["name"] for tool in tools_for_scope(source_scope())} == {"library.get"}


def test_write_tools_are_hidden_without_an_explicit_grant(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    provider = FakeProvider([
        {"tool_calls": [{"name": "task.propose", "arguments": {"action": "create", "title": "Read Week 5", "course": COURSE, "evidence_source": "Course reading list", "evidence_path": SOURCE}}]},
        {"text": "I could not use an ungranted proposal tool."},
    ])

    result = RunController(context, provider).run(user_request(course_scope()))

    assert result.status == "completed"
    assert all(tool["name"] not in {"task.propose", "import.propose", "domain.propose", "study.create"} for tool in provider.requests[0].tools)
    tool_event = next(event for event in result.events if event.event_type.value == "tool_result")
    assert tool_event.data["ok"] is False
    assert tool_event.data["code"] == "tool_not_granted"


def test_granted_task_proposal_routes_through_review_without_writing(tmp_path: Path) -> None:
    from academia_os.assistant import ToolGrant

    context, root = make_context(tmp_path)
    grant = ToolGrant(tools=frozenset({"task.propose"}))
    provider = FakeProvider([
        {"tool_calls": [{"name": "task.propose", "arguments": {
            "action": "create",
            "title": "Read Week 5",
            "course": COURSE,
            "due_date": "2026-10-01",
            "evidence_source": "Course reading list",
            "evidence_path": SOURCE,
        }}]},
        {"text": "I prepared the proposal."},
    ])

    result = RunController(context, provider).run(user_request(course_scope()), grants=grant)

    assert result.status == "completed"
    assert "task.propose" in {tool["name"] for tool in provider.requests[0].tools}
    proposal = result.tool_results[0].data
    assert proposal["status"] == "approval_required"
    assert proposal["review_id"]
    assert not (root / "Fall 2026" / "SEMESTER_TASKS.md").exists()
    tool_event = next(event for event in result.events if event.event_type.value == "tool_result")
    assert tool_event.data["data"]["review_id"] == proposal["review_id"]
