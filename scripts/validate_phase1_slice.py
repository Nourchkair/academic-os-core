"""Validate the Phase 1 local change slice against a copied real workspace.

Usage:
    PYTHONPATH=. ../academic-os-core/.venv/bin/python scripts/validate_phase1_slice.py \
      --workspace /path/to/copied/university --semester "Fall 2026" --json

The workspace must be a copy. This script performs consequential local changes
inside that copy and never touches the original academic workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from academia_os.assignment_history import list_assignment_history, update_assignment_history
from academia_os.domain import DomainProjection
from academia_os.knowledge import KnowledgeService
from academia_os.knowledge.model import Assertion, ChangeSet, new_id, now
from academia_os.tasks import TaskStore


COURSE = "POL2108A - Modern Political Theory I"
ASSESSMENT_TITLE = "Second Essay"
LINKED_TASK_TITLE = "Finish Second Essay"


def _fail(message: str) -> None:
    raise AssertionError(message)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _academic_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ".academia" in relative.parts:
            continue
        result[relative.as_posix()] = _file_hash(path)
    return result


def _run_cli(profile: Path, *args: str) -> Any:
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    completed = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), *args, "--json"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        _fail(f"CLI failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


def _assessment(service: KnowledgeService) -> dict[str, Any]:
    view = service.course_view(COURSE)
    matches = [item for item in view["assessments"] if item["title"] == ASSESSMENT_TITLE]
    if len(matches) != 1:
        _fail(f"expected one {ASSESSMENT_TITLE!r} assessment, found {len(matches)}")
    return matches[0]


def _statuses(changeset: dict[str, Any]) -> dict[str, str]:
    return {item["type"]: item["status"] for item in changeset["result"]["operation_results"]}


def validate(workspace: Path, semester: str, profile: Path) -> dict[str, Any]:
    root = workspace.resolve()
    if not root.is_dir():
        raise ValueError(f"workspace not found: {root}")
    if not (root / "ACADEMIC_OS_RULES.md").is_file() or not (root / "COURSE_TEMPLATE").is_dir():
        raise ValueError("validation workspace is missing recognition markers")
    pre_hashes = _academic_hashes(root)
    domain_path = root / ".academia" / "domain.json"
    domain_before = _file_hash(domain_path) if domain_path.is_file() else None

    service = KnowledgeService(root, semester)
    migrated = service.migrate()
    if migrated["status"] != "complete":
        _fail("migration did not complete")
    if _academic_hashes(root) != pre_hashes:
        _fail("migration changed an existing academic file outside .academia")
    if domain_before is not None and _file_hash(domain_path) != domain_before:
        _fail("migration rewrote domain.json")

    courses = ["LSR 1100-A00 - Introduction to Leisure Studies", "POL 2107A - Introduction to Political Thought", COURSE]
    course_views = {course: service.course_view(course) for course in courses}
    if any(not view["assessments"] for view in course_views.values()):
        _fail("a copied course did not produce any assessments")

    assessment = _assessment(service)
    original_due = assessment["fields"]["due_date"]["value"]
    if original_due != "2026-11-12":
        _fail(f"unexpected copied Second Essay deadline: {original_due}")
    history = list_assignment_history(root, semester, COURSE)
    second = next(item for item in history if item["title"] == ASSESSMENT_TITLE)
    if second["due_date"] != original_due:
        _fail("history record and knowledge view disagree before validation")

    # A real conflict: a recent professor announcement says Nov 18 while the
    # canonical history record says Nov 12. It must remain visible and must not
    # be overwritten by the student report.
    service.store.append_assertion(Assertion(
        id="assertion:validation-professor",
        subject_type="assessment",
        subject_id=assessment["id"],
        subject_label=ASSESSMENT_TITLE,
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
    conflicted = _assessment(service)["fields"]["due_date"]
    if conflicted["value"] != original_due or conflicted["resolution"] != "conflict":
        _fail("the conflicting professor announcement did not remain visible")

    task_store = TaskStore(root, semester)
    linked_task = next(item for item in task_store.list() if item["title"] == LINKED_TASK_TITLE)
    if linked_task["due_date"] != original_due:
        _fail("linked task does not match the assessment before validation")
    service.link_task(
        course_id=COURSE,
        assessment_id=assessment["id"],
        task_id=linked_task["id"],
        mode="mirror_deadline",
    )
    independent_task = task_store.create(title="Independent essay outline", course_id=COURSE, due_date=original_due)
    other_course_task = task_store.create(
        title="LSR independent milestone",
        course_id="LSR 1100-A00 - Introduction to Leisure Studies",
        due_date=original_due,
    )

    first = service.propose_deadline_change(
        course_id=COURSE,
        assessment_id=assessment["id"],
        new_date="2026-11-20",
        source_kind="student_report",
        source_label="Student report from validation",
    )
    if len(first["operations"]) != 2:
        _fail(f"expected assessment plus one linked-task operation, got {len(first['operations'])}")
    if not any(item["type"] == "task.set_due" and item["target"]["entity_id"] == linked_task["id"] for item in first["operations"]):
        _fail("linked task was not included")
    if any(item["target"].get("entity_id") in {independent_task["id"], other_course_task["id"]} for item in first["operations"] if item["type"] == "task.set_due"):
        _fail("an unlinked task was included")
    if len(first["conflicts"]) < 2:
        _fail("the proposal did not preserve both the owner conflict and the proposed change")

    required = next(item for item in first["operations"] if item["required"])
    service.approve_changeset(first["id"], operation_ids=[required["id"]])
    first_result = service.execute_changeset(first["id"])
    if first_result["status"] != "verified":
        _fail(f"first partial change did not verify: {first_result['status']}")
    if _statuses(first_result) != {"assessment.set_deadline": "verified", "task.set_due": "skipped"}:
        _fail(f"unexpected first operation states: {_statuses(first_result)}")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == ASSESSMENT_TITLE)["due_date"] != "2026-11-20":
        _fail("the assessment owner did not update to Nov 20")
    if task_store.get(linked_task["id"])["due_date"] != original_due:
        _fail("the skipped linked task moved")
    if task_store.get(independent_task["id"])["due_date"] != original_due:
        _fail("the independent task moved")
    if task_store.get(other_course_task["id"])["due_date"] != original_due:
        _fail("the other-course task moved")
    domain = service.domain()
    projected_assignments = [
        item for item in domain.list("assignment")
        if str(item.get("course_id")) == COURSE and item.get("title") == ASSESSMENT_TITLE
    ]
    projected_deadlines = [
        item for item in domain.list("deadline")
        if str(item.get("course_id")) == COURSE and item.get("title") == ASSESSMENT_TITLE
    ]
    if projected_assignments and any(item.get("deadline") != "2026-11-20" for item in projected_assignments):
        _fail("the extracted assessment projection did not follow the approved deadline")
    if projected_deadlines and any(item.get("date") != "2026-11-20" for item in projected_deadlines):
        _fail("the extracted deadline projection did not follow the approved deadline")
    link = next(item for item in service.links(COURSE)["links"] if item["task_id"] == linked_task["id"])
    if link["status"] != "paused":
        _fail("the skipped linked task's link was not paused")

    # A second change must not include the paused link.
    second_change = service.propose_deadline_change(
        course_id=COURSE,
        assessment_id=assessment["id"],
        new_date="2026-11-22",
        source_kind="student_report",
    )
    if any(item["type"] == "task.set_due" for item in second_change["operations"]):
        _fail("a paused link was included in the next change")
    service.approve_changeset(second_change["id"])
    second_result = service.execute_changeset(second_change["id"])
    if second_result["status"] != "verified":
        _fail(f"second change did not verify: {second_result['status']}")

    reverted_second = service.reverse_changeset(second_change["id"])
    if reverted_second["status"] != "reverted":
        _fail(f"second reversal did not complete: {reverted_second['status']}")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == ASSESSMENT_TITLE)["due_date"] != "2026-11-20":
        _fail("second reversal did not restore Nov 20")

    reverted_first = service.reverse_changeset(first["id"])
    if reverted_first["status"] != "reverted":
        _fail(f"first reversal did not complete: {reverted_first['status']}")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == ASSESSMENT_TITLE)["due_date"] != original_due:
        _fail("first reversal did not restore the original Nov 12")
    if projected_assignments and any(item.get("deadline") != original_due for item in domain.list("assignment") if item.get("id") in {projection.get("id") for projection in projected_assignments}):
        _fail("first reversal did not restore the extracted assessment projection")
    if projected_deadlines and any(item.get("date") != original_due for item in domain.list("deadline") if item.get("id") in {projection.get("id") for projection in projected_deadlines}):
        _fail("first reversal did not restore the extracted deadline projection")
    if link["status"] != "paused":
        _fail("reversal silently resumed a paused link")

    # Repeated change after reversal: old projections are superseded, not
    # accumulated as duplicate active values.
    repeated = service.propose_deadline_change(
        course_id=COURSE,
        assessment_id=assessment["id"],
        new_date="2026-11-24",
        source_kind="student_report",
    )
    service.approve_changeset(repeated["id"])
    repeated_result = service.execute_changeset(repeated["id"])
    if repeated_result["status"] != "verified":
        _fail(f"repeated change did not verify: {repeated_result['status']}")
    active = service.store.list_assertions(subject_id=assessment["id"], field="due_date", status="active")
    active_student = [item for item in active if item["source_kind"] == "student_report"]
    if len(active_student) != 1 or active_student[0]["value"] != "2026-11-24":
        _fail(f"repeated changes left duplicate or wrong active student assertions: {active_student}")
    conflict_after = _assessment(service)["fields"]["due_date"]
    if conflict_after["resolution"] != "conflict" or conflict_after["value"] != "2026-11-24":
        _fail("the professor conflict did not survive repeated changes")
    if projected_assignments and any(item.get("deadline") != "2026-11-24" for item in domain.list("assignment") if item.get("id") in {projection.get("id") for projection in projected_assignments}):
        _fail("repeated change did not update the extracted assessment projection")
    if projected_deadlines and any(item.get("date") != "2026-11-24" for item in domain.list("deadline") if item.get("id") in {projection.get("id") for projection in projected_deadlines}):
        _fail("repeated change did not update the extracted deadline projection")

    # Application restart: new process reads the same durable state.
    restarted = _run_cli(profile, "knowledge", "view", "--course", COURSE, "--semester", semester)
    restarted_assessment = next(item for item in restarted["assessments"] if item["title"] == ASSESSMENT_TITLE)
    if restarted_assessment["fields"]["due_date"]["value"] != "2026-11-24":
        _fail("a restarted process did not read the updated value")
    listed = _run_cli(profile, "change", "list", "--course", COURSE, "--semester", semester)
    if not any(item["status"] == "verified" for item in listed["changesets"]):
        _fail("a restarted process did not read the ChangeSet journal")

    # Crash after the target write but before verification. Recovery must verify
    # the after-state without writing it again.
    crash_change = service.propose_deadline_change(
        course_id=COURSE,
        assessment_id=assessment["id"],
        new_date="2026-11-26",
        source_kind="student_report",
    )
    service.approve_changeset(crash_change["id"])
    raw = service.get_changeset(crash_change["id"])
    raw["status"] = "executing"
    raw["operations"][0]["status"] = "executing"
    service.store.save_changeset(ChangeSet.from_dict(raw))
    service.update_history_deadline(
        course_id=COURSE,
        record_id=second["id"],
        before="2026-11-24",
        after="2026-11-26",
        actor="user",
    )
    recovered = _run_cli(profile, "change", "recover", "--semester", semester)
    if recovered["recovered_changesets"] != 1:
        _fail(f"recovery did not find the interrupted change: {recovered}")
    recovered_change = service.get_changeset(crash_change["id"])
    if recovered_change["status"] != "verified" or recovered_change["operations"][0]["status"] != "verified":
        _fail("recovery did not verify the after-state")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == ASSESSMENT_TITLE)["due_date"] != "2026-11-26":
        _fail("recovery changed the verified value")

    # A linked task failure must leave the assessment verified and the task
    # retryable; retry from a new process must touch only the failed operation.
    retry_task = task_store.create(title="Finish Second Essay retry", course_id=COURSE, due_date="2026-11-26")
    service.link_task(
        course_id=COURSE,
        assessment_id=assessment["id"],
        task_id=retry_task["id"],
        mode="mirror_deadline",
    )
    retry_change = service.propose_deadline_change(
        course_id=COURSE,
        assessment_id=assessment["id"],
        new_date="2026-11-28",
        source_kind="student_report",
    )
    service.approve_changeset(retry_change["id"])

    original_update = TaskStore.update_due_date_if_unchanged
    calls = {"count": 0}

    def flaky(self, task_id, *, before, after, actor="user"):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated task write failure")
        return original_update(self, task_id, before=before, after=after, actor=actor)

    TaskStore.update_due_date_if_unchanged = flaky
    try:
        failed = service.execute_changeset(retry_change["id"])
    finally:
        TaskStore.update_due_date_if_unchanged = original_update
    if failed["status"] != "partially_applied":
        _fail(f"expected a partial failure, got {failed['status']}")
    if _statuses(failed) != {"assessment.set_deadline": "verified", "task.set_due": "failed"}:
        _fail(f"unexpected failure states: {_statuses(failed)}")
    retried = _run_cli(profile, "change", "retry", retry_change["id"], "--semester", semester)
    if retried["status"] != "verified":
        _fail(f"retry did not verify: {retried['status']}")
    if task_store.get(retry_task["id"])["due_date"] != "2026-11-28":
        _fail("retry did not update the task")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == ASSESSMENT_TITLE)["due_date"] != "2026-11-28":
        _fail("retry changed the already-verified assessment")

    final = _assessment(service)["fields"]["due_date"]
    return {
        "status": "passed",
        "workspace": str(root),
        "semester": semester,
        "courses": {course: len(view["assessments"]) for course, view in course_views.items()},
        "migration_created_assertions": migrated["created_assertions"],
        "original_due": original_due,
        "final_due": final["value"],
        "final_resolution": final["resolution"],
        "final_verification": final["verification"],
        "linked_task_final_due": task_store.get(linked_task["id"])["due_date"],
        "independent_task_final_due": task_store.get(independent_task["id"])["due_date"],
        "other_course_task_final_due": task_store.get(other_course_task["id"])["due_date"],
        "paused_link_status": next(item for item in service.links(COURSE)["links"] if item["task_id"] == linked_task["id"])["status"],
        "crash_recovery": "verified_after_state",
        "failure_retry": "verified_after_retry",
        "restart": "read_from_new_process",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.workspace, args.semester, args.profile)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
