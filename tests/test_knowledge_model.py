from __future__ import annotations

from pathlib import Path

import pytest

from academia_os.assignment_history import add_assignment_history, list_assignment_history, update_assignment_history
from academia_os.domain import Assignment, Deadline, DomainProjection, Evidence
from academia_os.knowledge import KnowledgeService
from academia_os.knowledge.model import Assertion, new_id, now
from academia_os.tasks import TaskStore


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "University"
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    (course / "01_COURSE" / "syllabus.md").write_text("# Syllabus\nSecond Essay due November 12, 2026.", encoding="utf-8")
    return root, course


def _history(root: Path, course: Path, **overrides):
    values = {"kind": "essay", "title": "Second Essay", "status": "planned", "due_date": "2026-11-12"}
    values.update(overrides)
    return add_assignment_history(root, "Fall 2026", course.name, values)


def _assessment_id(record: dict) -> str:
    return f"assessment:history:{record['id']}"


def _link(service: KnowledgeService, course: Path, record: dict, task: dict):
    return service.link_task(
        course_id=course.name,
        assessment_id=_assessment_id(record),
        task_id=task["id"],
        mode="mirror_deadline",
    )


def test_history_owner_resolves_recorded_value_and_preserves_legacy_provenance(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")

    migrated = service.migrate()
    assert migrated["created_assertions"] == 1

    view = service.course_view(course.name)
    assessment = view["assessments"][0]
    assert assessment["id"] == _assessment_id(record)
    assert assessment["owner"]["kind"] == "assignment_history"
    due = assessment["fields"]["due_date"]
    assert due["value"] == "2026-11-12"
    assert due["resolution"] == "recorded"
    assert due["verification"] == "unverified"
    assert due["source_kind"] == "legacy_record"

    assertion = service.store.list_assertions(subject_id=_assessment_id(record), field="due_date")[0]
    assert assertion["source_kind"] == "legacy_record"
    assert assertion["verification"] == "unverified"
    assert assertion["legacy"]["record_basis"] == "user-confirmed"


def test_domain_deadline_is_a_projection_not_a_second_owner(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    evidence = Evidence(
        source="Syllabus",
        source_path=str(course / "01_COURSE" / "syllabus.md"),
        confidence="current-confirmed",
        authority="course syllabus",
    )
    domain = DomainProjection(root / ".academia" / "domain.json")
    domain.upsert(Assignment(
        id="essay-domain", course_id=course.name, title="Second Essay", deadline="2026-11-12", weight="25%",
        instructions_source=None, rubric_source=None, submission_method=None, status=None, evidence=evidence,
    ))
    domain.upsert(Deadline(
        id="deadline-domain", course_id=course.name, title="Second Essay", date="2026-11-12", time=None,
        type="assignment", evidence=evidence,
    ))
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")

    view = service.course_view(course.name)
    assessments = [item for item in view["assessments"] if item["title"] == "Second Essay"]
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment["id"] == _assessment_id(record)
    assert assessment["owner"]["kind"] == "assignment_history"
    alias_kinds = {alias["kind"] for alias in assessment["aliases"]}
    assert {"domain_assignment", "deadline_projection"} <= alias_kinds
    assert view["standalone_deadlines"] == []


def test_conflicting_assertion_does_not_overwrite_owner(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    service.migrate()
    service.store.append_assertion(Assertion(
        id=new_id("assertion"),
        subject_type="assessment",
        subject_id=_assessment_id(record),
        subject_label="Second Essay",
        field="due_date",
        value="2026-11-20",
        value_type="date",
        source_kind="student_report",
        authority_scope=["assessment.due_date"],
        specificity="exact",
        verification="unverified",
        confidence="likely",
        observed_at=now(),
        created_at=now(),
        created_by="user",
        status="active",
    ))

    due = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert due["value"] == "2026-11-12"
    assert due["resolution"] == "conflict"
    assert due["alternatives"][0]["value"] == "2026-11-20"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-12"


def test_assertion_only_value_can_be_derived_or_flagged_for_confirmation(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    service = KnowledgeService(root, "Fall 2026")
    subject_id = "assessment:assertion:test"

    def assertion(value: str, assertion_id: str) -> Assertion:
        return Assertion(
            id=assertion_id,
            subject_type="assessment",
            subject_id=subject_id,
            subject_label="Instructor-announced quiz",
            field="due_date",
            value=value,
            value_type="date",
            source_kind="student_report",
            authority_scope=["assessment.due_date"],
            specificity="exact",
            verification="unverified",
            confidence="likely",
            observed_at="2026-11-16T12:00:00+00:00",
            created_at="2026-11-16T12:00:00+00:00",
            created_by="user",
            status="active",
            metadata={"course_id": course.name},
        )

    service.store.append_assertion(assertion("2026-11-20", "assertion:one"))
    first = service.assessment_view(subject_id)["assessment"]["fields"]["due_date"]
    assert first["value"] == "2026-11-20"
    assert first["resolution"] == "derived"

    service.store.append_assertion(assertion("2026-11-21", "assertion:two"))
    second = service.assessment_view(subject_id)["assessment"]["fields"]["due_date"]
    assert second["resolution"] == "needs_confirmation"
    assert second["value"] in {"2026-11-20", "2026-11-21"}
    assert len(second["conflicts"]) == 2


def test_matching_task_is_not_linked_automatically(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    service.migrate()

    assert service.links(course.name)["links"] == []
    changeset = service.propose_deadline_change(
        course_id=course.name,
        assessment_id=_assessment_id(record),
        new_date="2026-11-20",
    )
    assert not any(operation["type"] == "task.set_due" for operation in changeset["operations"])
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-12"


def test_link_requires_explicit_matching_deadline(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Independent draft", course_id=course.name, due_date="2026-11-10")
    service = KnowledgeService(root, "Fall 2026")

    with pytest.raises(ValueError, match="equal the assessment deadline"):
        _link(service, course, record, task)
    assert service.links(course.name)["links"] == []


def test_agent_can_propose_but_not_approve_or_link(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(
        course_id=course.name,
        assessment_id=_assessment_id(record),
        new_date="2026-11-20",
        actor="agent:codex",
        channel="assistant",
    )
    with pytest.raises(PermissionError):
        service.approve_changeset(changeset["id"], actor="agent:codex", channel="assistant")
    with pytest.raises(PermissionError):
        service.approve_changeset(changeset["id"], actor="system", channel="internal")
    with pytest.raises(PermissionError):
        service.link_task(course_id=course.name, assessment_id=_assessment_id(record), task_id=task["id"], mode="mirror_deadline", actor="agent:codex", channel="assistant")


def test_agent_can_execute_after_user_approval(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(
        course_id=course.name,
        assessment_id=_assessment_id(record),
        new_date="2026-11-20",
        actor="agent:codex",
        channel="assistant",
    )
    service.approve_changeset(changeset["id"], actor="user", channel="dashboard")
    result = service.execute_changeset(changeset["id"], actor="agent:codex", channel="assistant")
    assert result["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"


def test_full_change_updates_owner_and_linked_task_and_is_idempotent(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    independent = TaskStore(root, "Fall 2026").create(title="Draft outline", course_id=course.name, due_date="2026-11-10")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)

    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    assert [operation["type"] for operation in changeset["operations"]] == ["assessment.set_deadline", "task.set_due"]
    before_apply = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert before_apply["value"] == "2026-11-12"
    assert before_apply["resolution"] == "recorded"
    assert before_apply["conflicts"] == []
    service.approve_changeset(changeset["id"])
    result = service.execute_changeset(changeset["id"])

    assert result["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-20"
    assert TaskStore(root, "Fall 2026").get(independent["id"])["due_date"] == "2026-11-10"
    after_apply = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert after_apply["value"] == "2026-11-20"
    assert after_apply["resolution"] == "recorded"
    assert after_apply["source_kind"] == "student_report"
    assert after_apply["source"]["source_kind"] == "student_report"
    assert after_apply["verification"] == "unverified"
    assert after_apply["conflicts"] == []
    again = service.execute_changeset(changeset["id"])
    assert again["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"


def test_partial_approval_skips_task_and_pauses_link(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    required = next(operation for operation in changeset["operations"] if operation["required"])
    service.approve_changeset(changeset["id"], operation_ids=[required["id"]])
    result = service.execute_changeset(changeset["id"])

    assert result["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-12"
    link = service.links(course.name)["links"][0]
    assert link["status"] == "paused"
    assert link["paused_by_change_id"] == changeset["id"]
    skipped = next(item for item in result["result"]["operation_results"] if item["type"] == "task.set_due")
    assert skipped["status"] == "skipped"
    assert skipped["skip_effect_applied"] is True
    with pytest.raises(ValueError, match="does not currently match"):
        service.resume_link(link_id=link["id"])
    TaskStore(root, "Fall 2026").update(task["id"], due_date="2026-11-20")
    resumed = service.resume_link(link_id=link["id"])
    assert resumed["status"] == "active"


def test_later_edit_blocks_execution(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-15"})

    result = service.execute_changeset(changeset["id"])
    assert result["status"] == "failed"
    assert result["result"]["operation_results"][0]["status"] == "conflict"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-15"


def test_amendment_invalidates_approval_and_rebuilds_candidate(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    old_assertion_id = changeset["operations"][0]["target"]["assertion_id"]

    amended = service.amend_deadline_change(changeset["id"], new_date="2026-11-21")
    assert amended["version"] == 2
    assert amended["status"] == "proposed"
    assert amended["approval"]["status"] == "pending"
    assert amended["operations"][0]["after"] == "2026-11-21"
    assert amended["operations"][0]["target"]["assertion_id"] != old_assertion_id
    assert service.store.get_assertion(old_assertion_id)["status"] == "rejected"

    service.approve_changeset(amended["id"])
    result = service.execute_changeset(amended["id"])
    assert result["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-21"


def test_retry_only_reapplies_the_failed_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])

    original = TaskStore.update_due_date_if_unchanged
    calls = {"count": 0}

    def flaky(self, task_id, *, before, after, actor="user"):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated task write failure")
        return original(self, task_id, before=before, after=after, actor=actor)

    monkeypatch.setattr(TaskStore, "update_due_date_if_unchanged", flaky)
    first = service.execute_changeset(changeset["id"])
    assert first["status"] == "partially_applied"
    statuses = {item["type"]: item["status"] for item in first["result"]["operation_results"]}
    assert statuses == {"assessment.set_deadline": "verified", "task.set_due": "failed"}

    retried = service.retry_changeset(changeset["id"])
    assert retried["status"] == "verified"
    statuses = {item["type"]: item["status"] for item in retried["result"]["operation_results"]}
    assert statuses == {"assessment.set_deadline": "verified", "task.set_due": "verified"}
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-20"


def test_required_failure_blocks_dependent_task(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-15"})

    result = service.execute_changeset(changeset["id"])
    assert result["status"] == "failed"
    statuses = {item["type"]: item["status"] for item in result["result"]["operation_results"]}
    assert statuses == {"assessment.set_deadline": "conflict", "task.set_due": "blocked"}
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-12"


def test_cancelled_proposal_does_not_leave_a_candidate_conflict(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    assertion_id = changeset["operations"][0]["target"]["assertion_id"]
    assert service.store.get_assertion(assertion_id)["status"] == "candidate"

    cancelled = service.cancel_changeset(changeset["id"])
    assert cancelled["status"] == "cancelled"
    assert service.store.get_assertion(assertion_id)["status"] == "rejected"
    due = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert due["value"] == "2026-11-12"
    assert due["conflicts"] == []


def test_independent_source_disagreement_survives_an_applied_change(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    service.migrate()
    service.store.append_assertion(Assertion(
        id="assertion:professor",
        subject_type="assessment",
        subject_id=_assessment_id(record),
        subject_label="Second Essay",
        field="due_date",
        value="2026-11-18",
        value_type="date",
        source_kind="professor_announcement",
        authority_scope=["assessment.due_date"],
        specificity="exact",
        verification="unverified",
        confidence="likely",
        observed_at="2026-11-15T12:00:00+00:00",
        created_at="2026-11-15T12:00:00+00:00",
        created_by="user",
        status="active",
    ))

    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    service.execute_changeset(changeset["id"])

    due = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert due["value"] == "2026-11-20"
    assert due["resolution"] == "conflict"
    assert due["alternatives"][0]["value"] == "2026-11-18"
    assert service.store.get_assertion("assertion:professor")["status"] == "active"


def test_crash_after_write_recovers_without_reapplying(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    from academia_os.knowledge.model import ChangeSet

    raw = service.get_changeset(changeset["id"])
    raw["status"] = "executing"
    raw["operations"][0]["status"] = "executing"
    service.store.save_changeset(ChangeSet.from_dict(raw))
    service.update_history_deadline(course_id=course.name, record_id=record["id"], before="2026-11-12", after="2026-11-20", actor="user")

    recovered = service.recover_incomplete()
    assert recovered["recovered_changesets"] == 1
    result = service.get_changeset(changeset["id"])
    assert result["status"] == "verified"
    assert result["operations"][0]["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"


def test_crash_before_write_returns_to_approved_then_retries(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    from academia_os.knowledge.model import ChangeSet

    raw = service.get_changeset(changeset["id"])
    raw["status"] = "executing"
    raw["operations"][0]["status"] = "executing"
    service.store.save_changeset(ChangeSet.from_dict(raw))

    service.recover_incomplete()
    recovered = service.get_changeset(changeset["id"])
    assert recovered["operations"][0]["status"] == "approved"
    result = service.execute_changeset(changeset["id"])
    assert result["status"] == "verified"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-20"


def test_reversal_restores_values_and_preserves_later_edit_conflict(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    service.execute_changeset(changeset["id"])

    reversed_value = service.reverse_changeset(changeset["id"])
    assert reversed_value["status"] == "reverted"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-12"
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-12"
    reversed_view = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert reversed_view["value"] == "2026-11-12"
    assert reversed_view["resolution"] == "recorded"
    assert reversed_view["conflicts"] == []

    # A later edit must block a second reversal rather than being overwritten.
    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-25"})
    second = service.reverse_changeset(changeset["id"])
    assert second["status"] == "reverted"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-25"


def test_reversal_conflict_after_later_edit(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    service.execute_changeset(changeset["id"])
    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-25"})

    result = service.reverse_changeset(changeset["id"])
    assert result["status"] == "reversal_conflict"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-25"


def test_migration_is_idempotent_and_records_external_edits(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    assert service.migrate()["created_assertions"] == 1
    assert service.migrate()["created_assertions"] == 0

    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-15"})
    refreshed = service.migrate()
    assert refreshed["created_assertions"] == 1
    assertions = service.store.list_assertions(subject_id=_assessment_id(record), field="due_date")
    assert any(assertion["source_kind"] == "external_edit" for assertion in assertions)
    assert service.migrate()["created_assertions"] == 0


def test_reverse_partial_change_keeps_failed_operation_failed(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    task = TaskStore(root, "Fall 2026").create(title="Finish Second Essay", course_id=course.name, due_date="2026-11-12")
    service = KnowledgeService(root, "Fall 2026")
    _link(service, course, record, task)
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    TaskStore(root, "Fall 2026").update(task["id"], due_date="2026-11-15")

    executed = service.execute_changeset(changeset["id"])
    assert executed["status"] == "partially_applied"
    assert next(item for item in executed["result"]["operation_results"] if item["type"] == "task.set_due")["status"] == "conflict"

    reverted = service.reverse_changeset(changeset["id"])
    assert reverted["status"] == "partially_reverted"
    assert list_assignment_history(root, "Fall 2026", course.name)[0]["due_date"] == "2026-11-12"
    assert TaskStore(root, "Fall 2026").get(task["id"])["due_date"] == "2026-11-15"


def test_engine_applied_change_is_not_mislabelled_as_external_edit(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    service.migrate()
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(changeset["id"])
    service.execute_changeset(changeset["id"])

    assert service.migrate()["created_assertions"] == 0
    assertions = service.store.list_assertions(subject_id=_assessment_id(record), field="due_date")
    assert not any(assertion["source_kind"] == "external_edit" for assertion in assertions)

    service.reverse_changeset(changeset["id"])
    assert service.migrate()["created_assertions"] == 0
    assertions = service.store.list_assertions(subject_id=_assessment_id(record), field="due_date")
    assert not any(assertion["source_kind"] == "external_edit" for assertion in assertions)

    update_assignment_history(root, "Fall 2026", course.name, record["id"], {"due_date": "2026-11-25"})
    assert service.migrate()["created_assertions"] == 1
    assertions = service.store.list_assertions(subject_id=_assessment_id(record), field="due_date")
    assert any(assertion["source_kind"] == "external_edit" for assertion in assertions)


def test_domain_owned_assessment_change_and_reversal(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    evidence = Evidence(
        source="Syllabus",
        source_path=str(course / "01_COURSE" / "syllabus.md"),
        confidence="current-confirmed",
        authority="course syllabus",
    )
    DomainProjection(root / ".academia" / "domain.json").upsert(Assignment(
        id="quiz-domain", course_id=course.name, title="Quiz 3", deadline="2026-11-19", weight="5%",
        instructions_source=None, rubric_source=None, submission_method=None, status=None, evidence=evidence,
    ))
    service = KnowledgeService(root, "Fall 2026")
    assessment_id = "assessment:domain:quiz-domain"
    view = service.course_view(course.name)
    assert view["assessments"][0]["owner"]["kind"] == "domain_projection"
    changeset = service.propose_deadline_change(course_id=course.name, assessment_id=assessment_id, new_date="2026-11-26")
    service.approve_changeset(changeset["id"])
    result = service.execute_changeset(changeset["id"])
    assert result["status"] == "verified"
    assert DomainProjection(root / ".academia" / "domain.json").get("assignment", "quiz-domain")["deadline"] == "2026-11-26"

    reversed_value = service.reverse_changeset(changeset["id"])
    assert reversed_value["status"] == "reverted"
    assert DomainProjection(root / ".academia" / "domain.json").get("assignment", "quiz-domain")["deadline"] == "2026-11-19"


def test_changed_source_is_flagged_as_stale(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    evidence = Evidence(
        source="Syllabus",
        source_path=str(course / "01_COURSE" / "syllabus.md"),
        confidence="current-confirmed",
        authority="course syllabus",
    )
    DomainProjection(root / ".academia" / "domain.json").upsert(Assignment(
        id="quiz-stale", course_id=course.name, title="Quiz 3", deadline="2026-11-19", weight="5%",
        instructions_source=None, rubric_source=None, submission_method=None, status=None, evidence=evidence,
    ))
    service = KnowledgeService(root, "Fall 2026")
    service.migrate()
    (course / "01_COURSE" / "syllabus.md").write_text("# Syllabus\nQuiz 3 may move.", encoding="utf-8")

    due = service.course_view(course.name)["assessments"][0]["fields"]["due_date"]
    assert due["value"] == "2026-11-19"
    assert any("source changed" in warning for warning in due["warnings"])


def test_new_proposal_supersedes_an_older_proposed_change(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    first = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    first_assertion = first["operations"][0]["target"]["assertion_id"]
    second = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-21")
    assert service.get_changeset(first["id"])["status"] == "superseded"
    assert service.store.get_assertion(first_assertion)["status"] == "rejected"
    assert second["status"] == "proposed"
    assert second["operations"][0]["after"] == "2026-11-21"


def test_approved_change_blocks_a_competing_new_proposal(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    first = service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-20")
    service.approve_changeset(first["id"])
    with pytest.raises(ValueError, match="approved change already exists"):
        service.propose_deadline_change(course_id=course.name, assessment_id=_assessment_id(record), new_date="2026-11-21")


def test_evidence_path_must_be_academic_material(tmp_path: Path) -> None:
    root, course = _workspace(tmp_path)
    record = _history(root, course)
    service = KnowledgeService(root, "Fall 2026")
    with pytest.raises(ValueError, match="academic material"):
        service.propose_deadline_change(
            course_id=course.name,
            assessment_id=_assessment_id(record),
            new_date="2026-11-20",
            evidence_path=str(root / ".academia" / "domain.json"),
        )
