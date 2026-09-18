from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .acquisition import browser_access_policy, capability_report, configured_watched_folders, import_file, scan_watched_folder, validate_import_destination
from .agent import build_agent_attention, build_agent_capabilities, build_agent_changes, build_agent_context
from .artifacts import create_generated_artifact
from .actions import ActionStore
from .activity import ActivityLog
from .attachment import assess_profile, attach_workspace, backup_profile, inspect_workspace
from .config import load_config, save_config, runtime_directory, validate_config
from .course_identity import resolve_course_identifier
from .discovery import discover_academic_folders
from .domain import ENTITY_TYPES, DomainProjection
from .file_preview import preview_file
from .library import filter_material, list_material
from .provenance import verify_source_metadata
from .review import ReviewQueue
from .semester import resolve_current_semester
from .settings import preview_config, update_config
from .workspace import build_workspace_snapshot
from .workflow import ApprovalWorkflow
from .web import DEFAULT_HOST, DEFAULT_PORT, serve_dashboard, validate_loopback_host
from installer.core import initialize_installation
from installer.migration import MigrationPlan, build_migration_plan, ensure_safe_text_target, execute_migration_plan, load_migration_plan, safe_atomic_write_text, validate_migration_source, write_migration_plan
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


def _semester_context(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, snapshot, profile_path = _context(args)
    semester = getattr(args, "semester", None)
    if semester and semester != snapshot["semester"]:
        snapshot = build_workspace_snapshot(config, persist=False, semester_override=semester)
    return config, snapshot, profile_path


def _agent_semester_context(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], Path]:
    profile_path = _profile_path(args)
    config = load_config(profile_path)
    semester = getattr(args, "semester", None)
    snapshot = build_workspace_snapshot(config, persist=False, semester_override=semester)
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
                "semester": args.semester or resolve_current_semester(timezone_name=args.timezone),
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


def _active_academic_root(config: dict[str, Any]) -> Path:
    return Path(config["academic"]["root_directory"]).expanduser().resolve()


def _lexical_migration_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _reject_migration_symlink_components(path: Path, label: str) -> None:
    path = _lexical_migration_path(path)
    for component in reversed(path.parents):
        if not os.path.lexists(component):
            break
        if os.path.islink(component):
            raise ValueError(f"migration {label} contains symlink component: {component}")
    if os.path.lexists(path) and os.path.islink(path):
        raise ValueError(f"migration {label} is a symlink: {path}")


def _validate_migration_directory(path: Path, label: str) -> Path:
    path = _lexical_migration_path(path)
    _reject_migration_symlink_components(path, label)
    if os.path.lexists(path) and not path.is_dir():
        raise ValueError(f"migration {label} is not a directory: {path}")
    return path


def _load_active_migration_plan(args: argparse.Namespace) -> tuple[MigrationPlan, Path]:
    config = load_config(_profile_path(args))
    runtime_root = runtime_directory(config)
    migration_directory = _validate_migration_directory(runtime_root / "migration", "active runtime migration directory")
    plan_path = _lexical_migration_path(args.plan)
    _reject_migration_symlink_components(plan_path, "plan")
    if os.path.lexists(plan_path) and plan_path.is_dir():
        raise ValueError(f"migration plan is a directory: {plan_path}")
    if migration_directory != plan_path and migration_directory not in plan_path.parents:
        raise ValueError("migration plan must be inside the active runtime migration directory")
    plan = load_migration_plan(plan_path)
    validate_migration_source(plan.source_root, runtime_root)
    if plan.academic_root != _active_academic_root(config):
        raise ValueError("migration plan academic root does not match the active profile workspace")
    return plan, plan_path


def _read_migration_report(path: Path) -> Any:
    path = _lexical_migration_path(path)
    _reject_migration_symlink_components(path, "report")
    if not os.path.lexists(path):
        return None
    if path.is_dir():
        raise ValueError(f"migration report is a directory: {path}")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read migration report {path}: {exc}") from exc


def _migration_indexes(args: argparse.Namespace, item_count: int) -> list[int]:
    supplied = [index for group in (args.item or []) for index in (group if isinstance(group, list) else [group])]
    indexes = supplied if supplied else list(range(item_count))
    if len(set(indexes)) != len(indexes):
        raise ValueError("migration item indexes must not be repeated")
    invalid = [index for index in indexes if index < 0 or index >= item_count]
    if invalid:
        raise ValueError(f"migration item index out of range: {invalid[0]}")
    return indexes


def _migration_plan(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(_profile_path(args))
    runtime_root = runtime_directory(config)
    source_root = validate_migration_source(args.source, runtime_root)
    plan = build_migration_plan(source_root, _active_academic_root(config), config["academic"]["semester"])
    paths = write_migration_plan(plan, runtime_root / "migration")
    value = plan.as_json()
    value.update({"plan_path": str(paths["json"]), "review_path": str(paths["markdown"]), "status": "planned", "action": "plan"})
    return value


def _migration_status(args: argparse.Namespace) -> dict[str, Any]:
    plan, plan_path = _load_active_migration_plan(args)
    report_path = plan_path.parent / "migration-report.json"
    value = plan.as_json()
    value.update(
        {
            "plan_path": str(plan_path),
            "report_path": str(report_path),
            "report": _read_migration_report(report_path),
            "status": "report_available" if report_path.is_file() else "ready",
            "action": "status",
        }
    )
    return value


def _migration_execute(args: argparse.Namespace) -> dict[str, Any]:
    plan, plan_path = _load_active_migration_plan(args)
    indexes = _migration_indexes(args, len(plan.items))
    if args.mode == "move" and (not args.apply or not args.confirm_move):
        raise ValueError("migration mode move requires both --apply and --confirm-move")
    report_path = plan_path.parent / "migration-report.json"
    if not args.apply:
        return {
            "action": "execute",
            "status": "confirmation_required",
            "applied": False,
            "mode": args.mode,
            "selected": len(indexes),
            "selected_indexes": indexes,
            "plan_path": str(plan_path),
            "report_path": str(report_path),
        }

    ensure_safe_text_target(report_path)
    result = execute_migration_plan(plan, items=[plan.items[index] for index in indexes], mode=args.mode)
    result.update(
        {
            "action": "execute",
            "status": "completed_with_failures" if result["failed"] else "completed",
            "applied": True,
            "selected_indexes": indexes,
            "plan_path": str(plan_path),
            "report_path": str(report_path),
        }
    )
    safe_atomic_write_text(report_path, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def _migration(args: argparse.Namespace) -> dict[str, Any]:
    if args.migration_command == "plan":
        return _migration_plan(args)
    if args.migration_command == "status":
        return _migration_status(args)
    if args.migration_command == "execute":
        return _migration_execute(args)
    raise ValueError(f"unsupported migration command: {args.migration_command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academia", description="Agent-neutral local Academia OS interface")
    parser.add_argument("--profile", type=Path, help="Path to the local Academia OS profile.json")
    # A bare `academia` command is the friendly dashboard shortcut.  Keeping
    # subparsers optional lets `main()` supply that default without changing
    # the explicit machine-facing command surface.
    sub = parser.add_subparsers(dest="command")

    for name in ("status", "courses", "today", "tasks", "inbox", "activity", "agents", "capabilities"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
        if name == "courses":
            command.add_argument("--semester", help="Read courses from a specific semester folder")
    agent = sub.add_parser("agent", help="Stable bounded context and change-feed interface for authorized agents")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_context = agent_sub.add_parser("context", help="Build bounded structured academic context")
    agent_context.add_argument("--scope", choices=("workspace", "semester", "course", "today"), default="workspace")
    agent_context.add_argument("--course", dest="course_id")
    agent_context.add_argument("--semester", help="Read context from a specific semester folder")
    agent_context.add_argument("--detail", choices=("compact", "standard", "deep"), default="standard")
    agent_context.add_argument("--json", action="store_true")
    agent_attention = agent_sub.add_parser("attention", help="Return unresolved decisions and retryable issues")
    agent_attention.add_argument("--course", dest="course_id")
    agent_attention.add_argument("--semester", help="Read attention for a specific semester folder")
    agent_attention.add_argument("--detail", choices=("compact", "standard", "deep"), default="standard")
    agent_attention.add_argument("--json", action="store_true")
    agent_changes = agent_sub.add_parser("changes", help="Read Activity changes after an optional cursor")
    agent_changes.add_argument("--since", help="Activity id or ISO timestamp cursor")
    agent_changes.add_argument("--limit", type=int, default=100)
    agent_changes.add_argument("--json", action="store_true")
    agent_capabilities = agent_sub.add_parser("capabilities", help="Return categorized agent capability boundaries")
    agent_capabilities.add_argument("--json", action="store_true")
    artifact = sub.add_parser("artifact", help="Create safe AI-generated secondary academic material")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_create = artifact_sub.add_parser("create", help="Create a new Markdown artifact in Academia's generated-material location")
    artifact_create.add_argument("--course", dest="course_id", required=True)
    artifact_create.add_argument("--semester", help="Semester containing the course; defaults to the active semester")
    artifact_create.add_argument("--kind", required=True, help="Artifact kind such as study_guide or reading_summary")
    artifact_create.add_argument("--title", required=True)
    artifact_create.add_argument("--content-file", required=True, help="UTF-8 Markdown/text file, or '-' to read stdin")
    artifact_create.add_argument("--source", action="append", default=[], help="Workspace file reference; may be repeated")
    artifact_create.add_argument("--domain-ref", action="append", default=[], help="Evidence-backed domain entity id; may be repeated")
    artifact_create.add_argument("--created-by", help="Optional audit attribution such as codex, hermes, or claude")
    artifact_create.add_argument("--json", action="store_true")
    semester = sub.add_parser("semester", help="Resolve the current semester using the shared calendar and timezone policy")
    semester.add_argument("--timezone", default="UTC")
    semester.add_argument("--json", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("action", choices=["list", "approve", "reject", "resolve", "decide", "execute"], nargs="?", default="list")
    review.add_argument("item_id", nargs="?")
    review.add_argument("decision", nargs="?", help="Typed decision such as use_new or choose_course:...")
    review.add_argument("--json", action="store_true")
    course = sub.add_parser("course")
    course.add_argument("course_id", nargs="?")
    course.add_argument("--json", action="store_true")
    domain = sub.add_parser("domain")
    domain.add_argument("entity_type", choices=ENTITY_TYPES, nargs="?")
    domain.add_argument("--json", action="store_true")
    library = sub.add_parser("library", help="List visible material in the active semester")
    library.add_argument("--category", choices=("all", "syllabi", "readings", "notes", "generated", "imports", "other"), default="all")
    library.add_argument("--course", dest="course_id")
    library.add_argument("--query", default="")
    library.add_argument("--semester", help="Read material from a specific semester folder")
    library.add_argument("--json", action="store_true")
    file_preview_command = sub.add_parser("file-preview", help="Read a bounded preview of one active-semester Library file")
    file_preview_command.add_argument("source", type=Path)
    file_preview_command.add_argument("--semester", help="Read the file from a specific semester folder")
    file_preview_command.add_argument("--json", action="store_true")
    extract = sub.add_parser("extract", help="Extract supported facts from an authoritative local source")
    extract_sub = extract.add_subparsers(dest="extract_type", required=True)
    syllabus = extract_sub.add_parser("syllabus", help="Preview or reconcile a local syllabus")
    syllabus.add_argument("source", type=Path)
    syllabus.add_argument("--course", required=True, help="Explicit recognized course context; Academia will not guess it")
    syllabus.add_argument("--verified-current", action="store_true", help="Treat direct facts as current-confirmed after the user verifies this is the current syllabus")
    syllabus.add_argument("--apply", action="store_true", help="Apply safe new projections and create Review items for conflicts")
    syllabus.add_argument("--json", action="store_true")
    workspace = sub.add_parser("workspace")
    workspace.add_argument("action", choices=["show", "discover", "inspect", "rebuild", "attach", "create"], nargs="?", default="show")
    workspace.add_argument("path", nargs="?", type=Path, help="Workspace path for inspect or attach")
    workspace.add_argument("--name", default="", help="Student name for an explicit workspace attachment")
    workspace.add_argument("--institution", default="", help="Institution for an explicit workspace attachment")
    workspace.add_argument("--program", default="", help="Program or faculty for an explicit workspace attachment")
    workspace.add_argument("--timezone", default="UTC", help="IANA timezone for an explicit workspace attachment")
    workspace.add_argument("--semester", default="", help="Explicit semester; omit to resolve it from the calendar and timezone")
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
    dashboard = sub.add_parser("dashboard", help="Serve the browser dashboard on the local machine")
    dashboard.add_argument("--host", default=DEFAULT_HOST, help="Loopback bind host (127.0.0.1, ::1, or localhost)")
    dashboard.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port; use 0 to select an available test port")
    dashboard.add_argument("--open", action="store_true", dest="open", help="Open the dashboard URL after the server is ready")
    dashboard.add_argument("--no-open", action="store_false", dest="open", help="Start the server without opening a browser")
    dashboard.set_defaults(open=True)
    imported = sub.add_parser("import", help="Copy one local file into a selected workspace inbox")
    imported.add_argument("source", type=Path)
    imported.add_argument("--destination", type=Path, required=True, help="Workspace inbox directory; source files are never moved")
    imported.add_argument("--source-label", help="Truthful provenance label for a staged source, instead of recording its temporary path")
    imported.add_argument("--uncertain", action="store_true", help="Keep the file in general intake and create a Review item")
    imported.add_argument("--json", action="store_true")
    migration = sub.add_parser("migration", help="Plan and execute safe legacy material migration")
    migration_sub = migration.add_subparsers(dest="migration_command", required=True)
    migration_plan = migration_sub.add_parser("plan", help="Create a reviewable migration plan")
    migration_plan.add_argument("source", type=Path)
    migration_plan.add_argument("--json", action="store_true")
    migration_status = migration_sub.add_parser("status", help="Read a migration plan and its report")
    migration_status.add_argument("--plan", type=Path, required=True)
    migration_status.add_argument("--json", action="store_true")
    migration_execute = migration_sub.add_parser("execute", help="Execute selected migration items")
    migration_execute.add_argument("--plan", type=Path, required=True)
    migration_execute.add_argument("--item", action="append", nargs="+", type=int, metavar="INDEX")
    migration_execute.add_argument("--mode", choices=("copy", "move"), default="copy")
    migration_execute.add_argument("--apply", action="store_true")
    migration_execute.add_argument("--confirm-move", action="store_true")
    migration_execute.add_argument("--json", action="store_true")
    return parser


def _human_status(value: dict[str, Any]) -> str:
    workspace = value["workspace"]
    return f"{workspace['student']['name']} · {workspace['semester']}\n{len(workspace['courses'])} course(s) · {value['review_count']} review item(s)\nWorkspace: {workspace['academic_root']}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.command = "dashboard"
        args.host = DEFAULT_HOST
        args.port = DEFAULT_PORT
        args.open = True
    try:
        if args.command == "status":
            value = _status(args); _emit(value, as_json=args.json, human=_human_status); return 0
        if args.command in {"courses", "today", "tasks", "course", "domain", "library", "file-preview", "extract", "workspace", "review", "inbox", "activity", "agents", "capabilities", "agent", "artifact", "semester", "watch", "import", "verify", "verify-source", "settings", "migration", "dashboard"}:
            return dispatch(args)
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False))
        else:
            print(f"academia: {exc}", file=sys.stderr)
        return 2
    return 2


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "dashboard":
        validate_loopback_host(args.host)
        serve_dashboard(host=args.host, port=args.port, open_browser=args.open, profile=args.profile)
        return 0
    if args.command == "migration":
        _emit(_migration(args), as_json=args.json)
        return 0
    if args.command == "agent":
        if args.agent_command == "capabilities":
            _emit(build_agent_capabilities(), as_json=args.json)
            return 0
        if args.agent_command == "changes":
            config = load_config(_profile_path(args))
            _emit(build_agent_changes(config, since=args.since, limit=args.limit), as_json=args.json)
            return 0
        config, snapshot, _ = _agent_semester_context(args)
        if args.agent_command == "context":
            value = build_agent_context(config, snapshot, scope=args.scope, detail=args.detail, course_id=args.course_id, semester=args.semester)
        elif args.agent_command == "attention":
            value = build_agent_attention(config, snapshot, detail=args.detail, course_id=args.course_id)
        else:
            raise ValueError(f"unsupported agent command: {args.agent_command}")
        _emit(value, as_json=args.json)
        return 0
    if args.command == "artifact":
        if args.artifact_command != "create":
            raise ValueError(f"unsupported artifact command: {args.artifact_command}")
        config, snapshot, _ = _context(args)
        if args.content_file == "-":
            content = sys.stdin.read()
        else:
            content_path = Path(args.content_file).expanduser()
            if content_path.is_symlink() or not content_path.is_file():
                raise ValueError("artifact content-file must be a regular local text file or '-'")
            content = content_path.read_text(encoding="utf-8")
        workspace_root = Path(snapshot["academic_root"]).expanduser().resolve()
        value = create_generated_artifact(
            workspace_root,
            semester=args.semester or snapshot["semester"],
            course_id=args.course_id,
            kind=args.kind,
            title=args.title,
            content=content,
            source_refs=args.source,
            domain_refs=args.domain_ref,
            created_by=args.created_by,
        )
        _emit(value, as_json=args.json)
        return 0
    if args.command == "semester":
        _emit({"semester": resolve_current_semester(timezone_name=args.timezone), "timezone": args.timezone}, as_json=args.json)
        return 0
    if args.command == "courses":
        _, snapshot, _ = _semester_context(args); _emit(snapshot["courses"], as_json=args.json); return 0
    if args.command == "today":
        _, snapshot, _ = _context(args); _emit(snapshot["today"], as_json=args.json); return 0
    if args.command == "tasks":
        _, snapshot, _ = _context(args); _emit(snapshot["tasks"], as_json=args.json); return 0
    if args.command == "course":
        _, snapshot, _ = _context(args)
        if not args.course_id:
            _emit(snapshot["courses"], as_json=args.json); return 0
        _emit(resolve_course_identifier(snapshot["courses"], args.course_id), as_json=args.json); return 0
    if args.command == "domain":
        _, snapshot, _ = _context(args)
        projection = DomainProjection(Path(snapshot["academic_root"]) / ".academia" / "domain.json")
        _emit(projection.list(args.entity_type), as_json=args.json); return 0
    if args.command == "library":
        _, snapshot, _ = _semester_context(args)
        items = list_material(Path(snapshot["academic_root"]), snapshot["semester"])
        _emit(filter_material(items, category=args.category, course_id=args.course_id, query=args.query), as_json=args.json); return 0
    if args.command == "file-preview":
        _, snapshot, _ = _semester_context(args)
        value = preview_file(args.source, workspace_root=Path(snapshot["academic_root"]), semester=snapshot["semester"])
        _emit(value, as_json=args.json); return 0
    if args.command == "extract":
        if args.extract_type != "syllabus":
            raise ValueError(f"unsupported extraction source type: {args.extract_type}")
        from .extraction import extract_syllabus
        from .extraction.reconcile import reconcile_syllabus
        config = load_config(_profile_path(args))
        workspace_root = Path(config["academic"]["root_directory"]).expanduser().resolve()
        state_root = workspace_root / ".academia"
        extraction = extract_syllabus(args.source, course_id=args.course, verified_current=args.verified_current)
        projection = DomainProjection(state_root / "domain.json")
        workflow = ApprovalWorkflow(
            actions=ActionStore(state_root / "actions.json"),
            reviews=ReviewQueue(state_root / "review.json"),
            activity=ActivityLog(state_root / "activity.jsonl"),
        )
        reconciliation = reconcile_syllabus(extraction, domain=projection, workflow=workflow, apply=args.apply)
        if args.apply:
            ActivityLog(state_root / "activity.jsonl").append(
                event_type="syllabus.reconciled" if extraction.status.value == "supported" else "syllabus.unsupported",
                title=f"Reconciled syllabus {Path(extraction.source.path).name}" if extraction.status.value == "supported" else f"Syllabus extraction unsupported: {Path(extraction.source.path).name}",
                course=args.course,
                source=extraction.source.path,
                confidence="current-confirmed" if args.verified_current else "likely",
                details={"source_type": "syllabus", "added_count": reconciliation.added_count, "duplicate_count": reconciliation.duplicate_count, "conflict_count": reconciliation.conflict_count},
                actor="system",
            )
        _emit({"applied": bool(args.apply), "extraction": extraction.as_dict(), "reconciliation": reconciliation.as_dict()}, as_json=args.json)
        return 0
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
            courses=snapshot.get("courses", []),
        )
        if args.action != "list":
            if not args.item_id:
                raise ValueError(f"review {args.action} requires an item id")
            if args.action == "decide":
                if not args.decision:
                    raise ValueError("review decide requires a decision")
                value = asdict(workflow.decide_review(args.item_id, args.decision))
            elif args.action == "execute":
                from .extraction.reconcile import execute_domain_change
                review_item = queue.get(args.item_id)
                if not review_item.action_proposal_id:
                    raise ValueError("review execute requires an action-linked Review item")
                projection = DomainProjection(state_root / "domain.json")
                value = asdict(workflow.execute_approved(review_item.action_proposal_id, lambda proposal: execute_domain_change(proposal, projection)))
            elif args.action == "approve":
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
        workspace_root = Path(snapshot["academic_root"])
        processing = ProcessingStore(workspace_root / ".academia" / "processing.json")
        for item in list_material(workspace_root, snapshot["semester"]):
            if item.get("category") != "imports":
                continue
            source = Path(str(item["path"]))
            try:
                signature = f"{source.stat().st_size}:{source.stat().st_mtime_ns}"
            except OSError:
                continue
            processing.detect(source, signature=signature)
        value = [asdict(item) for item in processing.pending()]
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
        destination = validate_import_destination(workspace_root, args.destination)
        from .processing import ProcessingStore
        processing = ProcessingStore(workspace_root / ".academia" / "processing.json")
        value = import_file(
            args.source,
            destination,
            processing,
            workspace_root=workspace_root,
            source_label=getattr(args, "source_label", None),
        )
        ActivityLog(workspace_root / ".academia" / "activity.jsonl").append(
            event_type="file.imported",
            title=f"Imported {Path(value['destination']).name}",
            details=value,
            source=value.get("source_label", str(args.source.expanduser().resolve())),
            confidence="unverified",
            actor="user",
        )
        if args.uncertain:
            review_details = {
                "filename": Path(value["destination"]).name,
                "proposed_course": None,
                "proposed_category": None,
                "proposed_destination": value["destination"],
                "evidence": "The user marked this import as not yet classified.",
                "confidence": "unverified",
                "original_file": value["original_file"],
                "preserve_original": True,
            }
            if "source_label" in value:
                review_details["source_type"] = value["source_type"]
                review_details["source_label"] = value["source_label"]
            review_item = ReviewQueue(workspace_root / ".academia" / "review.json").add(
                kind="import_classification",
                title=f"Choose a destination for {Path(value['destination']).name}",
                details=review_details,
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
        candidate, changes = update_config(config, updates, approve_structural=args.approve_structural) if args.apply else preview_config(config, updates)
        value = {"applied": False, "changes": changes, "requires_approval": any(change["structural"] for change in changes)}
        if args.apply:
            save_config(_profile_path(args), candidate); value["applied"] = True
        _emit(value, as_json=args.json); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
