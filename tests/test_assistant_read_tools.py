from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from academia_os.assistant import AssistantError, ReadContext, descriptor, descriptors, invoke
from academia_os.assistant.policy import PolicyDenied
from tests.test_agent_interface import prepared_workspace


def make_context(tmp_path: Path, *, hosted: bool = True) -> tuple[ReadContext, Path]:
    config, root, _ = prepared_workspace(tmp_path)
    context = ReadContext.create(config, hosted_model_allowed=hosted)
    return context, root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_registry_advertises_only_read_tools_with_stable_versions() -> None:
    tools = descriptors()
    names = {tool["name"] for tool in tools}
    assert names == {
        "workspace.summary",
        "course.list",
        "course.get",
        "task.list",
        "library.list",
        "library.get",
        "library.search_passages",
        "study.overview",
        "study.exam_scope",
        "review.attention",
        "activity.changes",
        "context.get",
    }
    assert all(tool["version"] == 1 for tool in tools)
    assert all(tool["permission"] == "read_local" for tool in tools)
    assert all(tool["side_effect"] == "none" for tool in tools)
    assert descriptor("library.get").disclosure.value == "hosted_model_eligible"


def test_workspace_course_task_and_library_reads(tmp_path: Path) -> None:
    context, root = make_context(tmp_path)

    summary = invoke("workspace.summary", {}, context).data
    assert summary["semester"] == "Fall 2026"
    assert summary["course_count"] == 1
    assert summary["workspace_exists"] is True

    courses = invoke("course.list", {}, context).data
    assert [course["id"] for course in courses] == ["POL 2103 - Politics"]

    course = invoke("course.get", {"course": "POL 2103"}, context).data
    assert course["name"] == "POL 2103 - Politics"

    tasks = invoke("task.list", {"course": "POL 2103"}, context).data
    assert any(task["title"] == "Read Week 4" for task in tasks)
    assert all(task["completed"] is False for task in tasks)

    library = invoke("library.list", {"course": "POL 2103", "query": "reading"}, context).data
    assert [item["name"] for item in library] == ["week-4-reading.md"]
    assert "content" not in library[0]

    item = invoke("library.get", {"item_id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"}, context)
    assert item.data["name"] == "week-4-reading.md"
    assert "Private source content stays out of context." in item.data["content"]
    assert item.data["identity"]["sha256"] == digest(root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md")
    assert item.scope is not None
    assert item.scope.course_id == "POL 2103 - Politics"


def test_passage_search_returns_citations_and_coverage(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    result = invoke(
        "library.search_passages",
        {
            "course": "POL 2103",
            "query": "Private source content",
            "source_ids": ["Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"],
            "limit": 4,
        },
        context,
    )

    assert result.data["course_id"] == "POL 2103 - Politics"
    assert result.data["chunks"]
    assert result.citations
    assert result.citations[0]["source_id"] == "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"
    assert result.data["coverage"]["selected_sources"] == 1


def test_study_attention_activity_and_context_reads(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)

    overview = invoke("study.overview", {"course": "POL 2103"}, context).data
    assert overview["course_id"] == "POL 2103 - Politics"
    assert overview["sets"] == []
    assert overview["progress_note"].startswith("Practice and self-assessment only")

    exams = invoke("study.exam_scope", {"course": "POL 2103"}, context).data
    assert exams == []

    attention = invoke("review.attention", {}, context).data
    assert attention["schema_version"] == 1
    assert attention["items"] == []

    changes = invoke("activity.changes", {"limit": 5}, context).data
    assert changes["schema_version"] == 1
    assert changes["next_cursor"] is None

    bounded = invoke("context.get", {"scope": "course", "course": "POL 2103", "detail": "compact"}, context).data
    assert bounded["scope"]["course_id"] == "POL 2103 - Politics"
    assert "Private source content stays out of context." not in str(bounded)


def test_read_tools_do_not_modify_academic_sources(tmp_path: Path) -> None:
    context, root = make_context(tmp_path)
    source = root / "Fall 2026" / "POL 2103 - Politics" / "05_REFERENCE" / "week-4-reading.md"
    status = root / "Fall 2026" / "POL 2103 - Politics" / "01_COURSE" / "Course_Status.md"
    before = (digest(source), digest(status))

    for name, arguments in (
        ("workspace.summary", {}),
        ("course.list", {}),
        ("task.list", {}),
        ("library.list", {}),
        ("library.get", {"item_id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"}),
        ("library.search_passages", {"course": "POL 2103", "query": "reading"}),
        ("study.overview", {"course": "POL 2103"}),
        ("study.exam_scope", {"course": "POL 2103"}),
        ("review.attention", {}),
        ("activity.changes", {}),
        ("context.get", {"scope": "workspace", "detail": "compact"}),
    ):
        invoke(name, arguments, context)

    assert (digest(source), digest(status)) == before


def test_invalid_arguments_unknown_tools_and_cross_course_sources_fail_closed(tmp_path: Path) -> None:
    context, root = make_context(tmp_path)
    (root / "Fall 2026" / "HIS 2101 - History" / "01_COURSE").mkdir(parents=True)
    context = ReadContext.create(context.config, hosted_model_allowed=True)

    with pytest.raises(AssistantError, match="unknown assistant tool"):
        invoke("not-a-tool", {}, context)
    with pytest.raises(AssistantError, match="required"):
        invoke("course.get", {}, context)
    with pytest.raises(AssistantError, match="unsupported field"):
        invoke("course.get", {"course": "POL 2103", "extra": True}, context)
    with pytest.raises(PolicyDenied, match="not found"):
        invoke("course.get", {"course": "UNKNOWN"}, context)
    with pytest.raises(AssistantError, match="study source"):
        invoke(
            "library.search_passages",
            {
                "course": "HIS 2101 - History",
                "query": "reading",
                "source_ids": ["Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"],
            },
            context,
        )
    with pytest.raises(AssistantError, match="hidden or parent"):
        invoke("library.get", {"item_id": "Fall 2026/../outside.md"}, context)


def test_hosted_disclosure_is_reported_but_does_not_block_local_reads(tmp_path: Path) -> None:
    local, _ = make_context(tmp_path, hosted=False)
    result = invoke("library.get", {"item_id": "Fall 2026/POL 2103 - Politics/05_REFERENCE/week-4-reading.md"}, local)
    assert result.data["content"]
