"""CLI surface for the local academic knowledge and ChangeSet engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config import SEMESTER_PATTERN, load_config
from .service import KnowledgeService


def add_parser(sub: argparse._SubParsersAction) -> None:
    knowledge = sub.add_parser("knowledge", help="Read and migrate the local academic knowledge layer")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    view = knowledge_sub.add_parser("view", help="Read resolved course assessments and conflicts")
    view.add_argument("--course", dest="course_id", required=True)
    view.add_argument("--semester")
    view.add_argument("--json", action="store_true")
    assessment = knowledge_sub.add_parser("assessment", help="Read one resolved assessment")
    assessment.add_argument("assessment_id")
    assessment.add_argument("--course", dest="course_id")
    assessment.add_argument("--semester")
    assessment.add_argument("--json", action="store_true")
    conflicts = knowledge_sub.add_parser("conflicts", help="Read unresolved assessment conflicts")
    conflicts.add_argument("--course", dest="course_id", required=True)
    conflicts.add_argument("--semester")
    conflicts.add_argument("--json", action="store_true")
    links = knowledge_sub.add_parser("links", help="Read explicit assessment/task links")
    links.add_argument("--course", dest="course_id", required=True)
    links.add_argument("--semester")
    links.add_argument("--json", action="store_true")
    migrate = knowledge_sub.add_parser("migrate", help="Index legacy academic records without changing them")
    migrate.add_argument("--semester")
    migrate.add_argument("--refresh", action="store_true", help="Append assertions for detected external edits")
    migrate.add_argument("--json", action="store_true")

    change = sub.add_parser("change", help="Propose, approve, execute, retry, or reverse an academic change")
    change_sub = change.add_subparsers(dest="change_command", required=True)
    propose = change_sub.add_parser("propose-deadline", help="Propose one assessment deadline change")
    propose.add_argument("--course", dest="course_id", required=True)
    propose.add_argument("--assessment", dest="assessment_id", required=True)
    propose.add_argument("--new-date", required=True)
    propose.add_argument("--source-kind", default="student_report", choices=("student_report", "professor_announcement", "original_document", "verified_external"))
    propose.add_argument("--source-label")
    propose.add_argument("--evidence-path")
    propose.add_argument("--evidence-locator")
    propose.add_argument("--evidence-excerpt")
    propose.add_argument("--note")
    propose.add_argument("--semester")
    propose.add_argument("--actor", default="user")
    propose.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard", "mcp", "assistant"))
    propose.add_argument("--json", action="store_true")
    link = change_sub.add_parser("link-task", help="Link one task to an assessment")
    link.add_argument("--course", dest="course_id", required=True)
    link.add_argument("--assessment", dest="assessment_id", required=True)
    link.add_argument("--task", dest="task_id", required=True)
    link.add_argument("--mode", default="mirror_deadline", choices=("mirror_deadline", "related"))
    link.add_argument("--semester")
    link.add_argument("--actor", default="user")
    link.add_argument("--json", action="store_true")
    pause = change_sub.add_parser("pause-link", help="Pause one explicit task link")
    pause.add_argument("link_id")
    pause.add_argument("--semester")
    pause.add_argument("--actor", default="user")
    pause.add_argument("--json", action="store_true")
    resume = change_sub.add_parser("resume-link", help="Resume one paused task link")
    resume.add_argument("link_id")
    resume.add_argument("--semester")
    resume.add_argument("--actor", default="user")
    resume.add_argument("--json", action="store_true")
    listing = change_sub.add_parser("list", help="List ChangeSets")
    listing.add_argument("--course", dest="course_id")
    listing.add_argument("--status")
    listing.add_argument("--semester")
    listing.add_argument("--json", action="store_true")
    show = change_sub.add_parser("show", help="Show one ChangeSet")
    show.add_argument("changeset_id")
    show.add_argument("--semester")
    show.add_argument("--json", action="store_true")
    amend = change_sub.add_parser("amend", help="Amend a proposed deadline change and invalidate its approval")
    amend.add_argument("changeset_id")
    amend.add_argument("--new-date")
    amend.add_argument("--note")
    amend.add_argument("--semester")
    amend.add_argument("--actor", default="user")
    amend.add_argument("--json", action="store_true")
    approve = change_sub.add_parser("approve", help="Record a student approval for a proposed ChangeSet")
    approve.add_argument("changeset_id")
    approve.add_argument("--operations", action="append", dest="operation_ids", help="Approved operation id; may be repeated")
    approve.add_argument("--note")
    approve.add_argument("--semester")
    approve.add_argument("--actor", default="user")
    approve.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard", "mcp", "assistant"))
    approve.add_argument("--json", action="store_true")
    execute = change_sub.add_parser("execute", help="Execute an approved ChangeSet")
    execute.add_argument("changeset_id")
    execute.add_argument("--semester")
    execute.add_argument("--actor", default="user")
    execute.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard", "mcp", "assistant", "internal"))
    execute.add_argument("--json", action="store_true")
    retry = change_sub.add_parser("retry", help="Retry only failed or blocked operations")
    retry.add_argument("changeset_id")
    retry.add_argument("--semester")
    retry.add_argument("--actor", default="user")
    retry.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard", "mcp", "assistant"))
    retry.add_argument("--json", action="store_true")
    cancel = change_sub.add_parser("cancel", help="Cancel a ChangeSet before execution")
    cancel.add_argument("changeset_id")
    cancel.add_argument("--semester")
    cancel.add_argument("--actor", default="user")
    cancel.add_argument("--json", action="store_true")
    reverse = change_sub.add_parser("reverse", help="Conditionally reverse an executed ChangeSet")
    reverse.add_argument("changeset_id")
    reverse.add_argument("--semester")
    reverse.add_argument("--actor", default="user")
    reverse.add_argument("--json", action="store_true")
    recover = change_sub.add_parser("recover", help="Recover interrupted ChangeSet execution from the journal")
    recover.add_argument("--semester")
    recover.add_argument("--json", action="store_true")


def run(args: argparse.Namespace, profile_path: Path | None = None) -> int:
    config = load_config(profile_path) if profile_path else load_config()
    root = Path(config["academic"]["root_directory"]).expanduser().resolve()
    semester = args.semester or config["academic"]["semester"]
    if SEMESTER_PATTERN.fullmatch(str(semester)) is None:
        raise ValueError("semester must use a term and four-digit year")
    service = KnowledgeService(root, str(semester))
    if args.command == "knowledge":
        value = _knowledge(service, args)
    else:
        value = _change(service, args)
    _emit(value, as_json=bool(getattr(args, "json", False)))
    return 0


def _knowledge(service: KnowledgeService, args: argparse.Namespace) -> Any:
    if args.knowledge_command == "view":
        return service.course_view(args.course_id)
    if args.knowledge_command == "assessment":
        return service.assessment_view(args.assessment_id, args.course_id)
    if args.knowledge_command == "conflicts":
        return service.conflicts(args.course_id)
    if args.knowledge_command == "links":
        return service.links(args.course_id)
    if args.knowledge_command == "migrate":
        return service.migrate(refresh=bool(args.refresh))
    raise ValueError(f"unsupported knowledge command: {args.knowledge_command}")


def _change(service: KnowledgeService, args: argparse.Namespace) -> Any:
    if args.change_command == "propose-deadline":
        return service.propose_deadline_change(
            course_id=args.course_id,
            assessment_id=args.assessment_id,
            new_date=args.new_date,
            source_kind=args.source_kind,
            source_label=args.source_label,
            evidence_path=args.evidence_path,
            evidence_locator=args.evidence_locator,
            evidence_excerpt=args.evidence_excerpt,
            note=args.note,
            actor=args.actor,
            channel=args.channel,
        )
    if args.change_command == "link-task":
        return service.link_task(
            course_id=args.course_id,
            assessment_id=args.assessment_id,
            task_id=args.task_id,
            mode=args.mode,
            actor=args.actor,
            channel="cli_user",
        )
    if args.change_command == "pause-link":
        return service.pause_link(link_id=args.link_id, actor=args.actor, channel="cli_user")
    if args.change_command == "resume-link":
        return service.resume_link(link_id=args.link_id, actor=args.actor, channel="cli_user")
    if args.change_command == "list":
        return service.list_changesets(course_id=args.course_id, status=args.status)
    if args.change_command == "show":
        return service.get_changeset(args.changeset_id)
    if args.change_command == "amend":
        return service.amend_deadline_change(
            args.changeset_id,
            new_date=args.new_date,
            note=args.note,
            actor=args.actor,
            channel="cli_user",
        )
    if args.change_command == "approve":
        return service.approve_changeset(
            args.changeset_id,
            operation_ids=args.operation_ids,
            actor=args.actor,
            channel=args.channel,
            note=args.note,
        )
    if args.change_command == "execute":
        return service.execute_changeset(args.changeset_id, actor=args.actor, channel=args.channel)
    if args.change_command == "retry":
        return service.retry_changeset(args.changeset_id, actor=args.actor, channel=args.channel)
    if args.change_command == "cancel":
        return service.cancel_changeset(args.changeset_id, actor=args.actor, channel="cli_user")
    if args.change_command == "reverse":
        return service.reverse_changeset(args.changeset_id, actor=args.actor, channel="cli_user")
    if args.change_command == "recover":
        return service.recover_incomplete()
    raise ValueError(f"unsupported change command: {args.change_command}")


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
        return
    print(_human(value))


def _human(value: Any) -> str:
    if not isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if "assessment" in value:
        assessment = value["assessment"]
        due = assessment.get("fields", {}).get("due_date", {})
        return f"{assessment.get('title')} · due {due.get('value') or 'not recorded'} ({due.get('resolution')})"
    if "assessments" in value:
        lines = [f"{value.get('course', {}).get('name') or 'Course'}"]
        for assessment in value.get("assessments", []):
            due = assessment.get("fields", {}).get("due_date", {})
            lines.append(f"- {assessment.get('title')}: {due.get('value') or 'no deadline'} ({due.get('resolution')})")
        for conflict in value.get("conflicts", []):
            lines.append(f"! {conflict.get('why')}")
        return "\n".join(lines)
    if "changesets" in value:
        return "\n".join(f"- {item.get('id')} · {item.get('status')} · {item.get('title')}" for item in value["changesets"]) or "No ChangeSets."
    if "operations" in value:
        lines = [f"{value.get('title')} · {value.get('status')}"]
        for operation in value.get("operations", []):
            lines.append(f"- {operation.get('label') or operation.get('type')}: {operation.get('before')} → {operation.get('after')} · {operation.get('status')}")
        return "\n".join(lines)
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)
