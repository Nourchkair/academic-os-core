"""CLI for pasted academic intake and candidate ChangeSets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config import SEMESTER_PATTERN, load_config
from .model import CANDIDATE_STATUSES
from .service import IntakeService


def add_parser(sub: argparse._SubParsersAction) -> None:
    intake = sub.add_parser("intake", help="Turn pasted academic announcements into candidate facts and ChangeSets")
    intake_sub = intake.add_subparsers(dest="intake_command", required=True)

    paste = intake_sub.add_parser("paste", help="Preserve one announcement and extract deadline candidates")
    paste.add_argument("--text", required=True)
    paste.add_argument("--course", dest="course_id")
    paste.add_argument("--source-kind", default="student_report", choices=("student_report", "professor_announcement"))
    paste.add_argument("--semester")
    paste.add_argument("--actor", default="user")
    paste.add_argument("--force", action="store_true")
    paste.add_argument("--json", action="store_true")

    document = intake_sub.add_parser("document", help="Scan one imported academic document for deadline candidates")
    document.add_argument("--source", required=True, help="Workspace-relative or absolute academic document path")
    document.add_argument("--course", dest="course_id")
    document.add_argument("--semester")
    document.add_argument("--actor", default="user")
    document.add_argument("--force", action="store_true")
    document.add_argument("--json", action="store_true")

    listing = intake_sub.add_parser("list", help="List intake candidates")
    listing.add_argument("--course", dest="course_id")
    listing.add_argument("--status", choices=tuple(sorted(CANDIDATE_STATUSES)))
    listing.add_argument("--semester")
    listing.add_argument("--json", action="store_true")

    show = intake_sub.add_parser("show", help="Show one intake candidate and its proposal")
    show.add_argument("candidate_id")
    show.add_argument("--semester")
    show.add_argument("--json", action="store_true")

    resolve = intake_sub.add_parser("resolve", help="Resolve an ambiguous candidate to a course and assessment")
    resolve.add_argument("candidate_id")
    resolve.add_argument("--course", dest="course_id")
    resolve.add_argument("--assessment", dest="assessment_id")
    resolve.add_argument("--semester")
    resolve.add_argument("--actor", default="user")
    resolve.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard"))
    resolve.add_argument("--json", action="store_true")

    propose = intake_sub.add_parser("propose", help="Create a ChangeSet from a resolved candidate")
    propose.add_argument("candidate_id")
    propose.add_argument("--semester")
    propose.add_argument("--actor", default="user")
    propose.add_argument("--channel", default="cli_user", choices=("cli_user", "dashboard", "mcp", "assistant"))
    propose.add_argument("--json", action="store_true")

    reject = intake_sub.add_parser("reject", help="Reject one intake candidate")
    reject.add_argument("candidate_id")
    reject.add_argument("--semester")
    reject.add_argument("--actor", default="user")
    reject.add_argument("--json", action="store_true")


def run(args: argparse.Namespace, profile_path: Path | None = None) -> int:
    config = load_config(profile_path) if profile_path else load_config()
    root = Path(config["academic"]["root_directory"]).expanduser().resolve()
    semester = args.semester or config["academic"]["semester"]
    if SEMESTER_PATTERN.fullmatch(str(semester)) is None:
        raise ValueError("semester must use a term and four-digit year")
    service = IntakeService(root, str(semester))
    if args.intake_command == "paste":
        value = service.submit_paste(
            text_value=args.text,
            course_id=args.course_id,
            source_kind=args.source_kind,
            actor=args.actor,
            force=bool(args.force),
        )
    elif args.intake_command == "list":
        value = service.list_candidates(course_id=args.course_id, status=args.status)
    elif args.intake_command == "document":
        value = service.submit_document(
            source_path=args.source,
            course_id=args.course_id,
            actor=args.actor,
            force=bool(args.force),
        )
    elif args.intake_command == "show":
        value = service.show_candidate(args.candidate_id)
    elif args.intake_command == "resolve":
        value = service.resolve_candidate(
            args.candidate_id,
            course_id=args.course_id,
            assessment_id=args.assessment_id,
            actor=args.actor,
            channel=args.channel,
        )
    elif args.intake_command == "propose":
        value = service.propose_candidate(args.candidate_id, actor=args.actor, channel=args.channel)
    elif args.intake_command == "reject":
        value = service.reject_candidate(args.candidate_id, actor=args.actor)
    else:
        raise ValueError(f"unsupported intake command: {args.intake_command}")
    _emit(value, as_json=bool(args.json))
    return 0


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
        return
    print(_human(value))


def _human(value: Any) -> str:
    if not isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if "intake" in value and "candidates" in value:
        lines = [f"Source: {value.get('intake', {}).get('source_path')}"]
        for candidate in value.get("candidates", []):
            lines.append(f"- {candidate.get('entity_title') or 'Assessment'}: {candidate.get('value') or 'needs a date'} · {candidate.get('status')}")
        for warning in value.get("warnings", []):
            lines.append(f"! {warning}")
        return "\n".join(lines)
    if "candidate" in value:
        candidate = value["candidate"]
        return f"{candidate.get('entity_title') or 'Assessment'} · {candidate.get('value') or 'no date'} · {candidate.get('status')}"
    if "changesets" in value:
        return "\n".join(f"- {item.get('id')} · {item.get('status')} · {item.get('title')}" for item in value["changesets"])
    if "title" in value and "operations" in value:
        return f"{value.get('title')} · {value.get('status')}"
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)
