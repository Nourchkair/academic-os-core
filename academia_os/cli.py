from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .acquisition import browser_access_policy, capability_report, configured_watched_folders, import_file, scan_watched_folder
from .actions import ActionStore
from .activity import ActivityLog
from .attachment import assess_profile, attach_workspace, backup_profile, inspect_workspace
from .config import load_config, save_config, runtime_directory, validate_config
from .discovery import discover_academic_folders
from .provenance import verify_source_metadata
from .review import ReviewQueue
from .settings import update_config
from .workspace import build_workspace_snapshot
from .workflow import ApprovalWorkflow
from installer.core import initialize_installation
from .version import __version__


def default_profile() -> Path:
    return Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser()


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _profile_path(args: argparse.Namespace) -> Path:
    return Path(args.profile).expanduser().resolve() if args.profile else default_profile().resolve()


def _context(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], Path]:
    profile_path = _profile_path(args)
    config = load_config(profile_path)
    snapshot = build_workspace_snapshot(config)
    return config, snapshot, profile_path


def _emit(value: Any, *, as_json: bool, human: Callable[[Any], str] | None = None) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    elif human:
        print(human(value))
    else:
        if isinstance(value, list):
            for item in value:
                print(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))
        else:
            print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _status(args: argparse.Namespace) -> dict[str, Any]:
    config, snapshot, profile_path = _context(args)
    state_root = Path(snapshot["academic_root"]) / ".academia"
    reviews = ReviewQueue(state_root / "review.json").list()
    activities = ActivityLog(state_root / "activity.jsonl").list(limit=5)
    return {
        "version": __version__,
        "profile": str(profile_path),
        "student": config["student"],
        "workspace": snapshot,
        "review_count": len(reviews),
        "recent_activity": [asdict(event) for event in activities],
        "acquisition": {"watched_folders": [str(path) for path in configured_watched_folders(config)], "browser": browser_access_policy(config), "capabilities": capability_report()},
        "agents": {
            "hermes": {"generic_agent_compatible": True, "dedicated_adapter": _hermes_status(config)},
            "codex": _generic_agent_status("Codex"),
            "claude": _generic_agent_status("Claude"),
            "chatgpt": _generic_agent_status("ChatGPT/Work"),
        },
    }


def _generic_agent_status(name: str) -> dict[str, Any]:
    return {
        "status": "available_without_dedicated_adapter",
        "generic_agent_compatible": True,
        "dedicated_adapter": "not required",
        "interface": "AGENTS.md + local academia CLI/API contract",
        "name": name,
    }


def _hermes_status(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from adapters.hermes.adapter import hermes_status

        return hermes_status(config)
    except Exception as exc:
        return {"name": "Hermes", "status": "unavailable", "message": str(exc)}


def _template_root() -> Path:
    candidate = Path(__file__).resolve().parents[1] / "templates" / "University"
    if not candidate.is_dir():
        raise ValueError("the reusable University workspace template is not available in this installation")
    return candidate


def _create_workspace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.path:
        raise ValueError("workspace create requires a destination path")
    if not args.name.strip() or not args.institution.strip():
        raise ValueError("name and institution are required to create a workspace")
    root = args.path.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("new workspace destination must be empty")
    profile_path = _profile_path(args)
    manifest = validate_config(
        {
            "schema_version": 2,
            "student": {"name": args.name.strip(), "institution": args.institution.strip(), "program": args.program.strip()},
            "academic": {
                "root_directory": str(root),
                "semester": args.semester or "Fall 2026",
                "timezone": args.timezone,
                "school_portal": "Not yet specified",
            },
            "runtime": {"install_directory": str(profile_path.parent)},
        }
    )
    result: dict[str, Any] = {
        "applied": False,
        "requires_confirmation": True,
        "academic_root": str(root),
        "profile_path": str(profile_path),
        "candidate": manifest,
        "academic_files_changed": False,
    }
    if not args.apply:
        return result
    profile_backup = None
    if profile_path.exists():
        profile_state, _ = assess_profile(profile_path)
        profile_backup = backup_profile(profile_path)
        profile_path.unlink()
        result["profile_state"] = profile_state
        result["backup_profile"] = str(profile_backup)
    try:
        initialized = initialize_installation(
            manifest,
            template_root=_template_root(),
            repo_root=Path(__file__).resolve().parents[1],
            allow_existing=False,
        )
    except Exception:
        if profile_backup and profile_backup.is_file():
            shutil.copy2(profile_backup, profile_path)
        raise
    result.update(initialized)
    result["applied"] = True
    result["requires_confirmation"] = False
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academia", description="Agent-neutral local Academia OS interface")
    parser.add_argument("--profile", type=Path, help="Path to the local Academia OS profile.json")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("status", "courses", "today", "tasks", "inbox", "activity", "agents", "capabilities"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("action", choices=["list", "approve", "reject", "resolve"], nargs="?", default="list")
    review.add_argument("item_id", nargs="?")
    review.add_argument("--json", action="store_true")
    course = sub.add_parser("course")
    course.add_argument("course_id", nargs="?")
    course.add_argument("--json", action="store_true")
    workspace = sub.add_parser("workspace")
    workspace.add_argument("action", choices=["show", "discover", "inspect", "rebuild", "attach", "create"], nargs="?", default="show")
    workspace.add_argument("path", nargs="?", type=Path, help="Workspace path for inspect or attach")
    workspace.add_argument("--name", default="", help="Student name for an explicit workspace attachment")
    workspace.add_argument("--institution", default="", help="Institution for an explicit workspace attachment")
    workspace.add_argument("--program", default="", help="Program or faculty for an explicit workspace attachment")
    workspace.add_argument("--timezone", default="UTC", help="IANA timezone for an explicit workspace attachment")
    workspace.add_argument("--semester", default="", help="Resolved semester such as Fall 2026")
    workspace.add_argument("--apply", action="store_true", help="Apply an explicit attachment after preview")
    workspace.add_argument("--json", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--json", action="store_true")
    verify_source = sub.add_parser("verify-source")
    verify_source.add_argument("--requested", type=Path, required=True)
    verify_source.add_argument("--retrieved", type=Path, required=True)
    verify_source.add_argument("--json", action="store_true")
    settings = sub.add_parser("settings")
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    show = settings_sub.add_parser("show"); show.add_argument("--json", action="store_true")
    update = settings_sub.add_parser("update")
    update.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    update.add_argument("--apply", action="store_true")
    update.add_argument("--approve-structural", action="store_true")
    update.add_argument("--json", action="store_true")
    watched = sub.add_parser("watch")
    watched.add_argument("--json", action="store_true")
    imported = sub.add_parser("import", help="Copy one local file into a selected workspace inbox")
    imported.add_argument("source", type=Path)
    imported.add_argument("--destination", type=Path, required=True, help="Workspace inbox directory; source files are never moved")
    imported.add_argument("--uncertain", action="store_true", help="Keep the file in general intake and create a Review item")
    imported.add_argument("--json", action="store_true")
    return parser


def _human_status(value: dict[str, Any]) -> str:
    workspace = value["workspace"]
    return f"{workspace['student']['name']} · {workspace['semester']}\n{len(workspace['courses'])} course(s) · {value['review_count']} review item(s)\nWorkspace: {workspace['academic_root']}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            value = _status(args); _emit(value, as_json=args.json, human=_human_status); return 0
        if args.command in {"courses", "today", "tasks", "course", "workspace", "review", "inbox", "activity", "agents", "capabilities", "watch", "import", "verify", "verify-source", "settings"}:
            return dispatch(args)
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False))
        else:
            print(f"academia: {exc}", file=sys.stderr)
        return 2
    return 2


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "courses":
        _, snapshot, _ = _context(args); _emit(snapshot["courses"], as_json=args.json); return 0
    if args.command == "today":
        _, snapshot, _ = _context(args); _emit(snapshot["today"], as_json=args.json); return 0
    if args.command == "tasks":
        _, snapshot, _ = _context(args); _emit(snapshot["tasks"], as_json=args.json); return 0
    if args.command == "course":
        _, snapshot, _ = _context(args)
        if not args.course_id:
            _emit(snapshot["courses"], as_json=args.json); return 0
        matches = [course for course in snapshot["courses"] if args.course_id.casefold() in {course["id"].casefold(), course["code"].casefold(), course["name"].casefold()}]
        if not matches:
            raise KeyError(f"course not found: {args.course_id}")
        _emit(matches[0], as_json=args.json); return 0
    if args.command == "workspace":
        if args.action == "inspect":
            if not args.path:
                raise ValueError("workspace inspect requires a path")
            value = inspect_workspace(args.path)
        elif args.action == "attach":
            if not args.path:
                raise ValueError("workspace attach requires a path")
            value = attach_workspace(
                args.path,
                _profile_path(args),
                name=args.name,
                institution=args.institution,
                program=args.program,
                timezone=args.timezone,
                semester=args.semester or None,
                apply=args.apply,
            )
        elif args.action == "create":
            value = _create_workspace(args)
        elif args.action == "discover":
            value = [asdict(item) for item in discover_academic_folders()]
            for item in value: item["path"] = str(item["path"])
        else:
            config, snapshot, _ = _context(args)
            if args.action == "rebuild":
                value = build_workspace_snapshot(config)
            else:
                value = {"academic_root": snapshot["academic_root"], "semester": snapshot["semester"], "exists": snapshot["workspace_exists"]}
        _emit(value, as_json=args.json); return 0
    if args.command == "review":
        _, snapshot, _ = _context(args)
        state_root = Path(snapshot["academic_root"]) / ".academia"
        queue = ReviewQueue(state_root / "review.json")
        workflow = ApprovalWorkflow(
            actions=ActionStore(state_root / "actions.json"),
            reviews=queue,
            activity=ActivityLog(state_root / "activity.jsonl"),
        )
        if args.action != "list":
            if not args.item_id:
                raise ValueError(f"review {args.action} requires an item id")
            if args.action == "approve":
                value = asdict(workflow.approve_review(args.item_id))
            elif args.action == "reject":
                value = asdict(workflow.reject_review(args.item_id))
            else:
                value = asdict(workflow.resolve_review(args.item_id))
        else:
            value = [asdict(item) for item in queue.list()]
        _emit(value, as_json=args.json); return 0
    if args.command == "inbox":
        _, snapshot, _ = _context(args)
        from .processing import ProcessingStore
        value = [asdict(item) for item in ProcessingStore(Path(snapshot["academic_root"]) / ".academia" / "processing.json").pending()]
        _emit(value, as_json=args.json); return 0
    if args.command == "activity":
        _, snapshot, _ = _context(args)
        value = [asdict(item) for item in ActivityLog(Path(snapshot["academic_root"]) / ".academia" / "activity.jsonl").list()]
        _emit(value, as_json=args.json); return 0
    if args.command == "agents":
        _emit(_status(args)["agents"], as_json=args.json); return 0
    if args.command == "capabilities":
        _emit(capability_report(), as_json=args.json); return 0
    if args.command == "watch":
        config, _, _ = _context(args)
        value = {str(folder): [str(path) for path in scan_watched_folder(folder)] for folder in configured_watched_folders(config)}
        _emit(value, as_json=args.json); return 0
    if args.command == "import":
        config, snapshot, _ = _context(args)
        workspace_root = Path(snapshot["academic_root"]).expanduser().resolve()
        destination = args.destination.expanduser().resolve()
        try:
            relative_destination = destination.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("import destination must be inside the configured academic workspace") from exc
        if destination == workspace_root or ".academia" in relative_destination.parts:
            raise ValueError("import destination must be a workspace inbox, not the workspace root or operational state")
        from .processing import ProcessingStore
        processing = ProcessingStore(workspace_root / ".academia" / "processing.json")
        value = import_file(args.source, destination, processing)
        ActivityLog(workspace_root / ".academia" / "activity.jsonl").append(
            event_type="file.imported",
            title=f"Imported {Path(value['destination']).name}",
            details=value,
            source=str(args.source.expanduser().resolve()),
            confidence="unverified",
            actor="user",
        )
        if args.uncertain:
            review_item = ReviewQueue(workspace_root / ".academia" / "review.json").add(
                kind="import_classification",
                title=f"Choose a destination for {Path(value['destination']).name}",
                details={
                    "destination": value["destination"],
                    "original_file": value["original_file"],
                    "reason": "The user marked this import as not yet classified.",
                    "preserve_original": True,
                },
                priority="normal",
            )
            value["review_item_id"] = review_item.id
        value["state_path"] = str(workspace_root / ".academia" / "processing.json")
        _emit(value, as_json=args.json); return 0
    if args.command == "verify-source":
        requested = json.loads(args.requested.read_text(encoding="utf-8")); retrieved = json.loads(args.retrieved.read_text(encoding="utf-8"))
        value = asdict(verify_source_metadata(requested, retrieved)); value["result"] = value["result"].value
        _emit(value, as_json=args.json); return 0
    if args.command == "verify":
        from installer.verify import verify_installation
        result = verify_installation(_profile_path(args)); _emit(result, as_json=args.json); return 0 if result["status"] == "pass" else 1
    if args.command == "settings":
        config = load_config(_profile_path(args))
        if args.settings_command == "show": _emit(config, as_json=args.json); return 0
        updates: dict[str, Any] = {}
        for expression in args.set:
            if "=" not in expression: raise ValueError(f"settings update expects KEY=VALUE: {expression}")
            key, value = expression.split("=", 1); updates[key] = _json_value(value)
        candidate, changes = update_config(config, updates, approve_structural=args.approve_structural)
        value = {"applied": False, "changes": changes, "requires_approval": any(change["structural"] for change in changes)}
        if args.apply:
            save_config(_profile_path(args), candidate); value["applied"] = True
        _emit(value, as_json=args.json); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
