from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from academia_os.actions import ActionStore, ActionType
from academia_os.activity import ActivityLog
from academia_os.review import ReviewQueue
from academia_os.workflow import ApprovalWorkflow
from tests.test_agent_interface import prepared_workspace

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TOOLS = {
    "academia_activity_changes",
    "academia_agent_context",
    "academia_attention",
    "academia_capabilities",
    "academia_courses",
    "academia_import_file",
    "academia_import_targets",
    "academia_library",
    "academia_processing_status",
    "academia_processing_detail",
    "academia_grade_history",
    "academia_study_exam_scope",
    "academia_study_overview",
    "academia_search_passages",
    "academia_propose_action",
    "academia_propose_calendar",
    "academia_propose_import",
    "academia_propose_task",
    "academia_read_library_item",
    "academia_review_decide",
    "academia_review_execute",
    "academia_review_item",
    "academia_status",
    "academia_tasks",
    "academia_today",
}


class McpServer:
    """Spawn the real stdio server and speak newline-delimited JSON-RPC."""

    def __init__(self, profile: Path, *, read_only: bool = False, proposal_only: bool = False, proposal_tools: list[str] | None = None, allow_actions: list[str] | None = None, download_intake: bool = False, semester: str | None = None, course: str | None = None) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT)
        command = [sys.executable, "-m", "academia_os", "--profile", str(profile), "mcp", "serve"]
        if read_only:
            command.append("--read-only")
        if proposal_only:
            command.append("--proposal-only")
        for proposal_tool in proposal_tools or []:
            command.extend(["--proposal-tool", proposal_tool])
        for action in allow_actions or []:
            command.extend(["--allow-action", action])
        if download_intake:
            command.append("--download-intake")
        if semester:
            command.extend(["--semester", semester])
        if course:
            command.extend(["--course", course])
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 0
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "academia-test", "version": "1.0"},
            },
        )
        self.notify("notifications/initialized")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}})
        return self._read()

    def _write(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        ready, _, _ = select.select([self.process.stdout], [], [], 30)
        if not ready:
            raise TimeoutError("MCP server did not answer within 30 seconds")
        line = self.process.stdout.readline()
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace")
            raise AssertionError(f"MCP server exited without a response: {stderr}")
        value = json.loads(line)
        assert isinstance(value, dict)
        return value

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()


@pytest.fixture()
def mcp(tmp_path: Path) -> tuple[McpServer, Path, Path]:
    _, root, profile = prepared_workspace(tmp_path)
    server = McpServer(profile)
    try:
        yield server, root, profile
    finally:
        server.close()


def call(server: McpServer, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    response = server.request("tools/call", {"name": name, "arguments": arguments or {}})
    assert "result" in response, response
    result = response["result"]
    assert isinstance(result, dict)
    return result


def call_json(server: McpServer, name: str, arguments: dict[str, Any] | None = None) -> Any:
    result = call(server, name, arguments)
    assert result.get("isError") is not True, result
    content = result.get("content")
    assert isinstance(content, list) and content
    assert content[0].get("type") == "text"
    return json.loads(content[0]["text"])


def call_error(server: McpServer, name: str, arguments: dict[str, Any] | None = None) -> str:
    result = call(server, name, arguments)
    assert result.get("isError") is True, result
    content = result.get("content")
    assert isinstance(content, list) and content
    assert content[0].get("type") == "text"
    message = content[0]["text"]
    assert isinstance(message, str) and message
    return message


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_mode_hides_and_rejects_write_tools(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    server = McpServer(profile, read_only=True)
    try:
        tools = server.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert names == EXPECTED_TOOLS - {
            "academia_review_decide",
            "academia_review_execute",
            "academia_import_file",
        "academia_propose_import",
        "academia_propose_task",
        "academia_propose_calendar",
        "academia_propose_action",
        }
        error = call_error(server, "academia_review_decide", {"review_id": "missing", "decision": "use_new"})
        assert "disabled in read-only mode" in error
        assert call_json(server, "academia_status")["workspace"]["semester"] == "Fall 2026"
    finally:
        server.close()


def test_calendar_proposal_tool_is_explicitly_granted(tmp_path: Path) -> None:
    _, _, profile = prepared_workspace(tmp_path)
    server = McpServer(profile, proposal_only=True, proposal_tools=["propose_calendar"])
    try:
        tools = server.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert "academia_propose_calendar" in names
        assert "academia_propose_task" not in names
        assert "academia_propose_import" not in names
    finally:
        server.close()

    denied = McpServer(profile, proposal_only=True, proposal_tools=["propose_task"])
    try:
        message = call_error(denied, "academia_propose_calendar", {"action": "create"})
        assert "not granted" in message
    finally:
        denied.close()


def test_calendar_mcp_proposal_creates_review_without_calling_calendar_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    from academia_os import mcp_server
    from academia_os.connectors import google as google_module
    google_connector_type = google_module.GoogleConnector

    class FakeGoogleConnector:
        validate_calendar_event = staticmethod(google_connector_type.validate_calendar_event)

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.writes = 0

        def status(self) -> dict[str, Any]:
            return {"auth_status": "authorized", "account_email": "student@example.edu"}

        def calendar_find_duplicates(self, _event: Any, *, exclude_event_id: str | None = None) -> list[dict[str, Any]]:
            return []

        def calendar_create(self, *_args: Any, **_kwargs: Any) -> None:
            self.writes += 1
            raise AssertionError("proposal tool must not write to Google")

    monkeypatch.setattr(google_module, "GoogleConnector", FakeGoogleConnector)
    result = mcp_server._call_tool(
        "academia_propose_calendar",
        {
            "action": "create",
            "summary": "Study block",
            "start": "2027-02-10T14:00:00Z",
            "end": "2027-02-10T15:00:00Z",
        },
        profile,
        proposal_only=True,
        proposal_tools={"academia_propose_calendar"},
    )

    assert result["status"] == "approval_required"
    assert result["review_id"]
    review = ReviewQueue(root / ".academia" / "review.json").get(result["review_id"])
    assert review.kind == "action_approval"
    assert review.details["action_type"] == "calendar_change"
    proposal = ActionStore(root / ".academia" / "actions.json").get(review.action_proposal_id)
    assert proposal.status == "proposed"


def test_initialize_and_ping(mcp: tuple[McpServer, Path, Path]) -> None:
    server, _, _ = mcp
    pong = server.request("ping")
    assert pong == {"jsonrpc": "2.0", "id": pong["id"], "result": {}}


def test_tools_list_is_stable_and_schemas_are_complete(mcp: tuple[McpServer, Path, Path]) -> None:
    server, _, _ = mcp
    response = server.request("tools/list")
    tools = response["result"]["tools"]
    assert isinstance(tools, list)
    names = [tool["name"] for tool in tools]
    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_TOOLS
    for tool in tools:
        assert isinstance(tool.get("description"), str) and tool["description"].strip()
        schema = tool.get("inputSchema")
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties"), dict)
        assert isinstance(schema.get("required"), list)
        assert schema.get("additionalProperties") is False
        assert set(schema["required"]) <= set(schema["properties"])
        if tool["name"] in {"academia_review_decide", "academia_review_execute", "academia_import_file", "academia_propose_import", "academia_propose_task", "academia_propose_calendar", "academia_propose_action"}:
            assert tool.get("annotations", {}).get("readOnlyHint") is False
        else:
            assert tool.get("annotations", {}).get("readOnlyHint") is True


def test_read_tools_return_bounded_workspace_data(mcp: tuple[McpServer, Path, Path]) -> None:
    server, root, _ = mcp

    status = call_json(server, "academia_status")
    assert status["workspace"]["semester"] == "Fall 2026"
    assert status["workspace"]["academic_root"] == str(root)

    courses = call_json(server, "academia_courses")
    assert [course["id"] for course in courses] == ["POL 2103 - Politics"]

    tasks = call_json(server, "academia_tasks")
    assert any(task["title"] == "Read Week 4" for task in tasks)

    context = call_json(server, "academia_agent_context", {"scope": "course", "course": "POL 2103", "detail": "compact"})
    assert context["schema_version"] == 1
    assert context["scope"]["course_id"] == "POL 2103 - Politics"
    assert "Private source content stays out of context." not in json.dumps(context)

    attention = call_json(server, "academia_attention")
    assert attention["schema_version"] == 1
    assert isinstance(attention["items"], list)

    library = call_json(server, "academia_library")
    reading = next(item for item in library["items"] if item["name"] == "week-4-reading.md")
    assert reading["id"] == "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"

    preview = call_json(server, "academia_read_library_item", {"id": reading["id"]})
    assert preview["name"] == "week-4-reading.md"
    assert "Private source content stays out of context." in preview["content"]

    processing = call_json(server, "academia_processing_status")
    assert processing == []

    targets = call_json(server, "academia_import_targets")
    assert targets["semester"] == "Fall 2026"
    assert {target["id"] for target in targets["targets"]} == {
        "Fall 2026/00_INBOX",
        "Fall 2026/POL 2103 - Politics/00_INBOX",
    }

    changes = call_json(server, "academia_activity_changes", {"limit": 10})
    assert changes["schema_version"] == 1
    assert changes["next_cursor"] is None


def test_read_tools_do_not_modify_academic_sources(mcp: tuple[McpServer, Path, Path]) -> None:
    server, root, _ = mcp
    reading = root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"
    status_file = root / "Fall 2026" / "POL 2103 - Politics" / "01_COURSE" / "Course_Status.md"
    before = (digest(reading), digest(status_file))

    call_json(server, "academia_status")
    call_json(server, "academia_courses")
    call_json(server, "academia_library")
    call_json(server, "academia_agent_context", {"scope": "workspace", "detail": "deep"})
    call_json(server, "academia_read_library_item", {"id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"})

    after = (digest(reading), digest(status_file))
    assert after == before


def test_invalid_arguments_return_structured_tool_errors(mcp: tuple[McpServer, Path, Path]) -> None:
    server, _, _ = mcp

    assert "scope" in call_error(server, "academia_agent_context", {"scope": "bogus"})
    assert "category" in call_error(server, "academia_library", {"category": "bogus"})
    assert "limit" in call_error(server, "academia_activity_changes", {"limit": 0})
    assert "Unknown workspace semester" in call_error(server, "academia_import_targets", {"semester": "Nope 2026"})
    assert "Unknown Academia MCP tool" in call_error(server, "academia_not_a_tool")


def test_write_tools_reject_inexact_or_missing_targets(mcp: tuple[McpServer, Path, Path]) -> None:
    server, root, _ = mcp
    inbox = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    before = sorted(path.name for path in inbox.iterdir()) if inbox.is_dir() else []

    assert "not open" in call_error(server, "academia_review_decide", {"review_id": "missing", "decision": "use_new"})
    assert "review item not found" in call_error(server, "academia_review_execute", {"review_id": "missing"})
    assert "source_path is not a regular file" in call_error(
        server,
        "academia_import_file",
        {"source_path": str(root / "not-a-file.md"), "target_id": "Fall 2026/POL 2103 - Politics/00_INBOX"},
    )
    assert "target_id" in call_error(
        server,
        "academia_import_file",
        {"source_path": str(root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"), "target_id": "Fall 2026/UNKNOWN/00_INBOX"},
    )

    after = sorted(path.name for path in inbox.iterdir()) if inbox.is_dir() else []
    assert after == before


def test_review_attention_and_exact_decision(mcp: tuple[McpServer, Path, Path]) -> None:
    server, root, _ = mcp
    course = "POL 2103 - Politics"
    workflow = ApprovalWorkflow(
        actions=ActionStore(root / ".academia" / "actions.json"),
        reviews=ReviewQueue(root / ".academia" / "review.json"),
        activity=ActivityLog(root / ".academia" / "activity.jsonl"),
    )
    _, review = workflow.propose(
        action_type=ActionType.DOMAIN_CHANGE,
        title="Review Research Essay deadline",
        course=course,
        details={"before": "2026-10-19", "after": "2026-10-22"},
        review_kind="deadline_conflict",
        review_details={
            "current_value": "2026-10-19",
            "proposed_value": "2026-10-22",
            "evidence": ["syllabus.md", "announcement.md"],
        },
    )

    attention = call_json(server, "academia_attention", {"course": course})
    item = next(entry for entry in attention["items"] if entry["id"] == review.id)
    assert {choice["id"] for choice in item["choices"]} == {"keep_current", "use_new"}

    shown = call_json(server, "academia_review_item", {"review_id": review.id})
    assert shown["id"] == review.id

    decided = call_json(
        server,
        "academia_review_decide",
        {"review_id": review.id, "decision": "keep_current"},
    )
    assert decided["review_id"] == review.id
    assert decided["decision"] == "keep_current"
    assert decided["status"] == "rejected"
    assert decided["requires_execution"] is False


def test_capability_report_mcp_metadata_matches_actual_tools(mcp: tuple[McpServer, Path, Path]) -> None:
    server, _, _ = mcp
    tools = server.request("tools/list")["result"]["tools"]
    actual = {tool["name"] for tool in tools}
    report = call_json(server, "academia_capabilities")
    mcp_report = report["implementation"]["mcp"]

    def normalize(name: str) -> str:
        return f"academia_{name}" if not name.startswith("academia_") else name

    advertised = {normalize(name) for name in mcp_report["read_tools"] + mcp_report["write_tools"] + mcp_report.get("proposal_tools", [])}
    assert advertised == actual


def test_read_search_study_and_grade_history_tools(tmp_path: Path) -> None:
    from academia_os.assignment_history import add_assignment_history

    _, root, profile = prepared_workspace(tmp_path)
    course = "POL 2103 - Politics"
    add_assignment_history(root, "Fall 2026", course, {
        "kind": "exam",
        "title": "Midterm",
        "status": "graded",
        "score": "54/60",
        "percentage": "90%",
        "letter_grade": "A+",
    })
    server = McpServer(profile)
    try:
        search = call_json(server, "academia_search_passages", {
            "course": course, "query": "private source content", "deep": True, "limit": 5,
        })
        assert search["data"]["chunks"]
        assert search["citations"]

        overview = call_json(server, "academia_study_overview", {"course": course})
        assert overview["tool"] == "study.overview"

        exam = call_json(server, "academia_study_exam_scope", {"course": course})
        assert exam["tool"] == "study.exam_scope"

        grades = call_json(server, "academia_grade_history", {"course": course})
        assert grades["graded_count"] == 1
        assert grades["records"][0]["score"] == "54/60"
        assert grades["records"][0]["percentage"] == "90%"
        assert grades["records"][0]["letter_grade"] == "A+"
    finally:
        server.close()


def test_trusted_task_and_history_actions_apply_without_review(tmp_path: Path) -> None:
    _, _root, profile = prepared_workspace(tmp_path)
    server = McpServer(profile, allow_actions=["tasks", "history"])
    try:
        exposed = {tool["name"] for tool in server.request("tools/list")["result"]["tools"]}
        assert "academia_task_create" in exposed
        assert "academia_review_decide" not in exposed
        assert "academia_review_execute" not in exposed
        assert "academia_import_file" not in exposed
        task = call_json(server, "academia_task_create", {"title": "Trusted task", "due_date": "2026-12-01"})
        assert task["title"] == "Trusted task"
        tasks = call_json(server, "academia_tasks", {})
        assert any(item["title"] == "Trusted task" for item in tasks)

        record = call_json(server, "academia_history_add", {
            "course": "POL 2103 - Politics",
            "kind": "exam",
            "title": "Trusted midterm",
            "status": "graded",
            "score": "54/60",
            "percentage": "90%",
            "letter_grade": "A+",
        })
        assert record["score"] == "54/60"
        assert record["letter_grade"] == "A+"
    finally:
        server.close()


def test_trusted_file_move_action_runs_and_verifies(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    source = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"
    destination = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading-moved.md"
    server = McpServer(profile, allow_actions=["files"])
    try:
        result = call_json(server, "academia_apply_action", {
            "action_type": "file_move",
            "details": {"source": source, "destination": destination},
            "title": "Trusted move",
        })
        assert result["result"]["status"] == "verified"
        assert (root / destination).is_file()
        assert not (root / source).exists()
    finally:
        server.close()


def test_trusted_study_create_uses_retrieved_citations(tmp_path: Path) -> None:
    _, _root, profile = prepared_workspace(tmp_path)
    server = McpServer(profile, allow_actions=["study"])
    try:
        search = call_json(server, "academia_search_passages", {
            "course": "POL 2103 - Politics", "query": "private source content", "deep": True, "limit": 5,
        })
        chunk = search["data"]["chunks"][0]
        chunk_id = chunk["id"]
        created = call_json(server, "academia_study_create", {
            "course": "POL 2103 - Politics",
            "source_ids": [chunk["source_id"]],
            "query": "private source content",
            "deep": True,
            "payload": {
                "kind": "quiz",
                "title": "Trusted practice",
                "items": [{
                    "kind": "short_answer",
                    "topic": "Reading",
                    "prompt": "What does the reading contain?",
                    "answer": "Private source content.",
                    "explanation": "The prepared reading contains this sentence.",
                    "citation_ids": [chunk_id],
                }],
            },
        })
        assert created["kind"] == "quiz"
        assert created["items"][0]["citations"][0]["id"] == chunk_id
    finally:
        server.close()


def test_processing_detail_returns_failure_context(tmp_path: Path) -> None:
    from academia_os.processing import ProcessingStore

    _, root, profile = prepared_workspace(tmp_path)
    source = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX" / "raw.pdf"
    source.parent.mkdir()
    source.write_bytes(b"raw")
    processing = ProcessingStore(root / ".academia" / "processing.json")
    record = processing.detect(source, signature="3:1")
    processing.begin(record.id)
    processing.fail(record.id, "synthetic extraction failure")
    server = McpServer(profile)
    try:
        value = call_json(server, "academia_processing_detail", {"record_id": record.id})
        assert value["id"] == record.id
        assert value["failure_reason"] == "synthetic extraction failure"
    finally:
        server.close()


def test_unknown_course_returns_error_without_killing_the_server(tmp_path: Path) -> None:
    _, _root, profile = prepared_workspace(tmp_path)
    server = McpServer(profile)
    try:
        message = call_error(server, "academia_grade_history", {"course": "LSR"})
        assert "course not found" in message

        # The same process must still answer the next request.
        status = call_json(server, "academia_status")
        assert status["workspace"]["academic_root"]
    finally:
        server.close()
