from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.activity import ActivityLog
from academia_os.assistant import ReadContext
from academia_os.assistant.tools.write import amend_task_proposal, execute_task_change, propose_task_change
from academia_os.tasks import TaskStore
from tests.test_agent_interface import prepared_workspace
from tests.test_assistant_writes import stores
from tests.test_mcp_server import McpServer, call_error, call_json

EVIDENCE = "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"


def _context(tmp_path: Path):
    config, root, profile = prepared_workspace(tmp_path)
    return ReadContext.create(config, hosted_model_allowed=False), config, root, profile


def _task_file(root: Path) -> Path:
    return root / "Fall 2026" / "SEMESTER_TASKS.md"


def test_task_create_proposal_writes_nothing_until_approved_and_executed(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)
    proposal = propose_task_change(
        context,
        action="create",
        title="Read Week 5",
        course="POL 2103",
        due_date="2026-10-01",
        due_time="09:00",
        evidence_source="Course reading list",
        evidence_path=EVIDENCE,
        confidence="current-confirmed",
        authority="course materials",
    )

    assert proposal["status"] == "approval_required"
    assert proposal["before"] == "No personal task"
    assert not _task_file(root).exists()
    _, actions, reviews = stores(root)
    stored = actions.get(proposal["proposal_id"])
    assert stored.action_type == "task_change"
    assert stored.details["action"] == "create"
    assert stored.details["task_after"]["title"] == "Read Week 5"
    assert reviews.get(proposal["review_id"]).details["action_type"] == "task_change"

    workflow, _, reviews = stores(root)
    workflow.decide_review(proposal["review_id"], "approve_action")
    verified = workflow.execute_approved(
        proposal["proposal_id"],
        lambda item: execute_task_change(item, workspace_root=root),
    )

    assert verified.status == "verified"
    assert reviews.get(proposal["review_id"]).status.value == "resolved"
    tasks = TaskStore(root, "Fall 2026").list()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["title"] == "Read Week 5"
    assert task["course_id"] == "POL 2103 - Politics"
    assert task["provenance"] == "AI-GENERATED"
    assert task["source"] == "Course reading list"
    assert task["status"] == "open"


def test_task_update_proposal_preserves_other_markdown(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)
    store = TaskStore(root, "Fall 2026")
    task = store.create(title="Draft outline", due_date="2026-10-10")
    path = _task_file(root)
    path.write_text(
        "# My semester tasks\n\nDo not touch this note.\n\n" + path.read_text(encoding="utf-8") + "\nTrailing note.\n",
        encoding="utf-8",
    )
    proposal = propose_task_change(
        context,
        action="update",
        task_id=task["id"],
        title="Draft the essay outline",
        due_date="2026-10-12",
        evidence_source="Instructor announcement",
        evidence_path=EVIDENCE,
    )
    assert store.get(task["id"])["title"] == "Draft outline"

    workflow, _, reviews = stores(root)
    workflow.decide_review(proposal["review_id"], "approve_action")
    workflow.execute_approved(proposal["proposal_id"], lambda item: execute_task_change(item, workspace_root=root))

    updated = TaskStore(root, "Fall 2026").get(task["id"])
    assert updated["title"] == "Draft the essay outline"
    assert updated["due_date"] == "2026-10-12"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# My semester tasks\n\nDo not touch this note.\n\n")
    assert text.endswith("\n\nTrailing note.\n")
    assert reviews.get(proposal["review_id"]).status.value == "resolved"


def test_stale_task_change_fails_without_overwriting_student_edit(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)
    store = TaskStore(root, "Fall 2026")
    task = store.create(title="Original", due_date="2026-10-10")
    proposal = propose_task_change(
        context,
        action="update",
        task_id=task["id"],
        due_date="2026-10-12",
        evidence_source="Course reading list",
        evidence_path=EVIDENCE,
    )
    store.update(task["id"], title="Student edited after proposal")

    workflow, actions, reviews = stores(root)
    workflow.decide_review(proposal["review_id"], "approve_action")
    with pytest.raises(ValueError, match="changed after approval"):
        workflow.execute_approved(proposal["proposal_id"], lambda item: execute_task_change(item, workspace_root=root))

    current = store.get(task["id"])
    assert current["title"] == "Student edited after proposal"
    assert current["due_date"] == "2026-10-10"
    assert actions.get(proposal["proposal_id"]).status == "failed"
    assert reviews.get(proposal["review_id"]).status.value == "open"


def test_invalid_task_proposals_are_rejected_before_review(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)

    with pytest.raises(ValueError, match="source path cannot be resolved"):
        propose_task_change(context, action="create", title="Read", evidence_source="Missing", evidence_path="Fall 2026/not-there.md")
    with pytest.raises(ValueError, match="due_date"):
        propose_task_change(context, action="create", title="Read", due_date="2026-02-31", evidence_source="Reading list", evidence_path=EVIDENCE)
    with pytest.raises(ValueError, match="only create or update"):
        propose_task_change(context, action="complete", task_id="one", evidence_source="Reading list", evidence_path=EVIDENCE)
    with pytest.raises(ValueError, match="exact task_id"):
        propose_task_change(context, action="update", title="Read", evidence_source="Reading list", evidence_path=EVIDENCE)
    assert stores(root)[2].list() == []
    assert not _task_file(root).exists()


def test_mcp_proposal_mode_creates_task_review_without_writing(tmp_path: Path) -> None:
    from academia_os.tasks import TaskStore
    from tests.test_mcp_scope import add_second_course

    _, root, profile = prepared_workspace(tmp_path)
    add_second_course(root)
    server = McpServer(profile, proposal_only=True, course="POL 2103")
    try:
        tools = {tool["name"] for tool in server.request("tools/list")["result"]["tools"]}
        assert "academia_propose_task" in tools
        assert "academia_import_file" not in tools

        proposal = call_json(server, "academia_propose_task", {
            "action": "create",
            "title": "Read Week 6",
            "due_date": "2026-10-08",
            "evidence_source": "Course reading list",
            "evidence_path": EVIDENCE,
        })
        assert proposal["status"] == "approval_required"
        assert proposal["review_id"]
        assert not _task_file(root).exists()
        _, actions, _ = stores(root)
        assert actions.get(proposal["proposal_id"]).details["task_after"]["course_id"] == "POL 2103 - Politics"
        assert "outside the selected course" in call_error(server, "academia_propose_task", {
            "action": "create",
            "title": "Wrong course",
            "course": "HIS 2101",
            "evidence_source": "Course reading list",
            "evidence_path": EVIDENCE,
        })
        his_task = TaskStore(root, "Fall 2026").create(title="HIS reading", course_id="HIS 2101")
        assert "outside the selected course" in call_error(server, "academia_propose_task", {
            "action": "update",
            "task_id": his_task["id"],
            "title": "Cross-course edit",
            "evidence_source": "Course reading list",
            "evidence_path": EVIDENCE,
        })
    finally:
        server.close()

    read_only = McpServer(profile, read_only=True)
    try:
        tools = {tool["name"] for tool in read_only.request("tools/list")["result"]["tools"]}
        assert "academia_propose_task" not in tools
    finally:
        read_only.close()


def test_cli_propose_task_decide_and_execute(tmp_path: Path) -> None:
    import json

    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    proposed = run_cli(
        profile,
        "assistant", "propose-task",
        "--action", "create",
        "--title", "Read Week 7",
        "--course", "POL 2103",
        "--due-date", "2026-10-15",
        "--evidence-source", "Course reading list",
        "--evidence-path", EVIDENCE,
        "--json",
    )
    assert proposed.returncode == 0, proposed.stderr
    proposal = json.loads(proposed.stdout)
    assert not _task_file(root).exists()

    attention = run_cli(profile, "agent", "attention", "--json")
    assert attention.returncode == 0, attention.stderr
    item = next(entry for entry in json.loads(attention.stdout)["needs_human_input"] if entry["id"] == proposal["review_id"])
    approval = next(choice for choice in item["choices"] if choice["action"]["requires_execution"])
    assert approval["executable"] is True
    assert approval["action"]["decision"] in {"approve", "approve_action"}
    assert approval["action"]["execution"]["type"] == "review_execute"

    decided = run_cli(profile, "review", "decide", proposal["review_id"], "approve_action", "--json")
    assert decided.returncode == 0, decided.stderr
    assert json.loads(decided.stdout)["status"] == "approved"
    assert not _task_file(root).exists()

    executed = run_cli(profile, "review", "execute", proposal["review_id"], "--json")
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)["status"] == "verified"
    tasks = TaskStore(root, "Fall 2026").list()
    assert [task["title"] for task in tasks] == ["Read Week 7"]
    assert tasks[0]["provenance"] == "AI-GENERATED"


def test_mcp_can_decide_and_execute_an_approved_task_change(tmp_path: Path) -> None:
    _, root, profile = prepared_workspace(tmp_path)
    proposal_server = McpServer(profile, proposal_only=True, course="POL 2103")
    try:
        proposal = call_json(proposal_server, "academia_propose_task", {
            "action": "create",
            "title": "Read Week 8",
            "evidence_source": "Course reading list",
            "evidence_path": EVIDENCE,
        })
    finally:
        proposal_server.close()
    assert not _task_file(root).exists()

    server = McpServer(profile)
    try:
        attention = call_json(server, "academia_attention")
        item = next(entry for entry in attention["needs_human_input"] if entry["id"] == proposal["review_id"])
        approve = next(choice for choice in item["choices"] if choice["action"].get("requires_execution"))
        decided = call_json(server, "academia_review_decide", {"review_id": proposal["review_id"], "decision": approve["id"]})
        assert decided["requires_execution"] is True
        assert not _task_file(root).exists()

        executed = call_json(server, "academia_review_execute", {"review_id": proposal["review_id"]})
        assert executed["verified"] is True
        assert [task["title"] for task in TaskStore(root, "Fall 2026").list()] == ["Read Week 8"]
    finally:
        server.close()


def test_amend_task_create_proposal_updates_exact_fields_and_executes(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)
    proposal = propose_task_change(
        context,
        action="create",
        title="Read Week 5",
        course="POL 2103",
        due_date="2026-10-01",
        evidence_source="Course reading list",
        evidence_path=EVIDENCE,
    )

    amended = amend_task_proposal(
        proposal["review_id"],
        workspace_root=root,
        title="Read Week 6",
        due_date="2026-10-08",
    )

    details = amended.details["proposal_details"]
    assert amended.title == "Add task: Read Week 6"
    assert stores(root)[1].get(proposal["proposal_id"]).title == "Add task: Read Week 6"
    assert details["task_after"]["title"] == "Read Week 6"
    assert details["task_after"]["due_date"] == "2026-10-08"
    assert details["after"] == "Read Week 6 · POL 2103 - Politics · due 2026-10-08"
    assert not _task_file(root).exists()
    events = [event.event_type for event in ActivityLog(root / ".academia" / "activity.jsonl").list()]
    assert "action.amended" in events

    workflow, _, _ = stores(root)
    workflow.decide_review(proposal["review_id"], "approve_action")
    workflow.execute_approved(proposal["proposal_id"], lambda item: execute_task_change(item, workspace_root=root))
    tasks = TaskStore(root, "Fall 2026").list()
    assert [task["title"] for task in tasks] == ["Read Week 6"]
    assert tasks[0]["due_date"] == "2026-10-08"


def test_amend_rejects_stale_or_no_longer_open_proposals(tmp_path: Path) -> None:
    context, _, root, _ = _context(tmp_path)
    store = TaskStore(root, "Fall 2026")
    task = store.create(title="Original", due_date="2026-10-10")
    proposal = propose_task_change(
        context,
        action="update",
        task_id=task["id"],
        due_date="2026-10-12",
        evidence_source="Course reading list",
        evidence_path=EVIDENCE,
    )
    store.update(task["id"], title="Student edited after proposal")
    with pytest.raises(ValueError, match="changed after the proposal"):
        amend_task_proposal(proposal["review_id"], workspace_root=root, due_date="2026-10-15")

    workflow, _, _ = stores(root)
    workflow.decide_review(proposal["review_id"], "approve_action")
    with pytest.raises(ValueError, match="only an open Review item"):
        amend_task_proposal(proposal["review_id"], workspace_root=root, due_date="2026-10-15")


def test_cli_amends_a_task_proposal_before_approval(tmp_path: Path) -> None:
    import json

    from tests.test_agent_interface import run_cli

    _, root, profile = prepared_workspace(tmp_path)
    proposed = run_cli(
        profile,
        "assistant", "propose-task",
        "--action", "create",
        "--title", "Read Week 5",
        "--course", "POL 2103",
        "--due-date", "2026-10-01",
        "--due-time", "09:00",
        "--evidence-source", "Course reading list",
        "--evidence-path", EVIDENCE,
        "--json",
    )
    assert proposed.returncode == 0, proposed.stderr
    proposal = json.loads(proposed.stdout)

    amended = run_cli(
        profile,
        "review", "amend", proposal["review_id"],
        "--task-title", "Read Week 6",
        "--clear-due-date",
        "--json",
    )
    assert amended.returncode == 0, amended.stderr
    value = json.loads(amended.stdout)
    assert value["details"]["proposal_details"]["task_after"]["title"] == "Read Week 6"
    assert value["details"]["proposal_details"]["task_after"]["due_date"] is None
    assert value["details"]["proposal_details"]["task_after"]["due_time"] is None
    assert not _task_file(root).exists()


def test_review_show_exposes_action_status_and_amended_details(tmp_path: Path) -> None:
    import json

    from tests.test_agent_interface import run_cli

    context, _, root, profile = _context(tmp_path)
    proposal = propose_task_change(
        context,
        action="create",
        title="Read Week 5",
        course="POL 2103",
        due_date="2026-10-01",
        evidence_source="Course reading list",
        evidence_path=EVIDENCE,
    )
    amend_task_proposal(proposal["review_id"], workspace_root=root, title="Read Week 6")
    shown = run_cli(profile, "review", "show", proposal["review_id"], "--json")
    assert shown.returncode == 0, shown.stderr
    value = json.loads(shown.stdout)
    assert value["action_status"] == "proposed"
    assert value["details"]["proposal_details"]["task_after"]["title"] == "Read Week 6"

    run_cli(profile, "review", "decide", proposal["review_id"], "approve_action", "--json")
    shown_again = run_cli(profile, "review", "show", proposal["review_id"], "--json")
    assert shown_again.returncode == 0, shown_again.stderr
    assert json.loads(shown_again.stdout)["action_status"] == "approved"
