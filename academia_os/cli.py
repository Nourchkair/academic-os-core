from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .acquisition import browser_access_policy, capability_report, configured_watched_folders, import_file, scan_watched_folder, validate_import_destination
from .assignment_history import add_assignment_history, apply_history_to_tasks, list_assignment_history, update_assignment_history
from .agent import _sanitize_value, build_agent_attention, build_agent_capabilities, build_agent_changes, build_agent_context
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
from .recommendations import get_playbook, get_recipe, list_playbooks, list_recommendations
from .review import ReviewQueue
from .semester import resolve_current_semester
from .settings import preview_config, update_config
from .tasks import TaskStateError, TaskStore, project_task
from .workspace import build_workspace_snapshot, load_startup_snapshot
from .workflow import ApprovalWorkflow
from .workflow_preferences import WorkflowPreferencesStore
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


def _application_root() -> Path:
    """Return the repository root or PyInstaller's bundled resource root."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    return Path(bundled_root).resolve() if bundled_root else Path(__file__).resolve().parents[1]


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


def _coursework_tasks(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(snapshot["academic_root"]).expanduser().resolve()
    tasks = list(snapshot.get("tasks", []))
    for course in snapshot.get("courses", []):
        records = list_assignment_history(root, str(snapshot["semester"]), str(course["id"]))
        tasks = apply_history_to_tasks(tasks, records, course_name=str(course.get("name", "")))
    return tasks


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
    if getattr(args, "fast", False):
        profile_path = _profile_path(args)
        config = load_config(profile_path)
        snapshot = load_startup_snapshot(config)
    else:
        config, snapshot, profile_path = _context(args)
    snapshot["tasks"] = _coursework_tasks(snapshot)
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
    candidate = _application_root() / "templates" / "University"
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
            "schema_version": 3,
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
            repo_root=_application_root(),
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


def _workflow_store(args: argparse.Namespace) -> WorkflowPreferencesStore:
    config = load_config(_profile_path(args))
    return WorkflowPreferencesStore(_active_academic_root(config))


def _workflow_preferences(args: argparse.Namespace) -> dict[str, Any] | list[dict[str, Any]]:
    store = _workflow_store(args)
    if args.workflow_command == "preferences":
        return {"schema_version": 1, "workflows": store.list()}
    if args.workflow_command == "show":
        return store.show(args.workflow_id)
    if args.workflow_command == "reset":
        reset_applied = store.reset(args.workflow_id)
        result = store.show(args.workflow_id)
        result["reset"] = True
        result["reset_applied"] = reset_applied
        return result
    if args.workflow_command == "set":
        preferences: dict[str, Any] = {}
        if args.preferences_json is not None:
            parsed = json.loads(args.preferences_json)
            if not isinstance(parsed, dict):
                raise ValueError("--preferences-json must contain a JSON object")
            preferences.update(parsed)
        for expression in args.set:
            if "=" not in expression:
                raise ValueError(f"workflow set expects KEY=VALUE: {expression}")
            key, value = expression.split("=", 1)
            if not key.strip():
                raise ValueError("workflow preference key must not be empty")
            preferences[key.strip()] = _json_value(value)
        replace_preferences = bool(args.replace_preferences)
        options: dict[str, Any] = {
            "preferences": preferences if (preferences or replace_preferences) else None,
            "replace_preferences": replace_preferences,
            "updated_by": args.updated_by,
        }
        if hasattr(args, "custom_instructions"):
            options["custom_instructions"] = args.custom_instructions
        if hasattr(args, "external_setup_notes"):
            options["external_setup_notes"] = args.external_setup_notes
        saved = store.set(args.workflow_id, **options)
        result = store.show(args.workflow_id)
        result["saved"] = True
        result["saved_preferences"] = saved
        return result
    raise ValueError(f"unsupported workflow command: {args.workflow_command}")


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


def _google_connector(args: argparse.Namespace) -> Any:
    from .connectors.google import GoogleConnector
    config = load_config(_profile_path(args))
    return GoogleConnector(runtime_directory(config) / "google_connector.json")


def _google_calendar_workflow(args: argparse.Namespace) -> tuple[Any, ApprovalWorkflow]:
    from .connectors.google import GoogleConnector

    config = load_config(_profile_path(args))
    workspace_root = Path(str(config["academic"]["root_directory"])).expanduser().resolve()
    state_root = workspace_root / ".academia"
    return (
        GoogleConnector(runtime_directory(config) / "google_connector.json"),
        ApprovalWorkflow(
            actions=ActionStore(state_root / "actions.json"),
            reviews=ReviewQueue(state_root / "review.json"),
            activity=ActivityLog(state_root / "activity.jsonl"),
        ),
    )


def _model_manager(args: argparse.Namespace) -> Any:
    from .model_connections import ModelConnectionManager
    config = load_config(_profile_path(args))
    return ModelConnectionManager(runtime_directory(config) / "model_connections.json")


def _models(args: argparse.Namespace) -> Any:
    manager = _model_manager(args)
    if args.models_command in {"list", "providers"}:
        value = manager.list()
        return value if args.models_command == "list" else value["catalog"]
    if args.models_command == "add":
        payload: dict[str, Any] = {}
        if getattr(args, "input_file", None):
            try:
                loaded = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("model provider input file is not valid JSON") from exc
            if not isinstance(loaded, dict):
                raise ValueError("model provider input file must contain a JSON object")
            payload = loaded
        provider = payload.get("provider") or args.provider
        api_key = payload.get("api_key") or args.api_key or ""
        if not api_key and getattr(args, "api_key_file", None):
            try:
                api_key = Path(args.api_key_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ValueError("model provider API key file could not be read") from exc
        base_url = payload.get("base_url") or args.base_url or ""
        name = payload.get("name") or args.name or ""
        return manager.add(provider=str(provider or ""), api_key=str(api_key), base_url=str(base_url), name=str(name))
    if args.models_command == "test":
        return manager.test(args.provider_id)
    if args.models_command == "remove":
        return manager.remove(args.provider_id)
    if args.models_command == "enable":
        return manager.set_enabled(args.provider_id, True)
    if args.models_command == "disable":
        return manager.set_enabled(args.provider_id, False)
    if args.models_command == "preferences":
        return manager.list()["preferences"]
    if args.models_command == "set-preferences":
        values = {role: getattr(args, role) for role in ("default", "fast", "deep", "vision", "image") if getattr(args, role) is not None}
        return manager.set_preferences(values)
    raise ValueError(f"unsupported models command: {args.models_command}")


def _connectors(args: argparse.Namespace) -> Any:
    if args.connector_command != "google":
        raise ValueError(f"unsupported connector: {args.connector_command}")
    connector = _google_connector(args)
    if args.google_command == "setup":
        try:
            value = json.loads(Path(args.client_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Google client JSON could not be read") from exc
        client = value.get("installed") if isinstance(value, dict) else None
        if not isinstance(client, dict):
            client = value.get("web") if isinstance(value, dict) else None
        if not isinstance(client, dict):
            client = value if isinstance(value, dict) else {}
        client_id = client.get("client_id")
        client_secret = client.get("client_secret")
        return connector.configure(client_id=client_id, client_secret=client_secret)
    if args.google_command == "status":
        return connector.status()
    if args.google_command == "authorize":
        from .native_bridge import run_lease

        def cancel_authorization() -> None:
            connector.cancel_authorize()

        with run_lease(_profile_path(args), "google", "google", cancel_authorization):
            return connector.authorize(open_browser=not args.no_open)
    if args.google_command == "oauth-status":
        return connector.oauth_status()
    if args.google_command == "oauth-cancel":
        from .native_bridge import request_cancel

        requested = request_cancel(_profile_path(args), "google", "google")
        if requested["cancelled"]:
            return connector.oauth_status()
        return connector.cancel_authorize()
    if args.google_command == "disconnect":
        return connector.disconnect()
    if args.google_command == "gmail":
        if args.gmail_command == "list":
            return connector.gmail_list(query=args.query or "", max_results=args.max_results)
        if args.gmail_command == "get":
            return connector.gmail_get(args.message_id)
    if args.google_command == "calendar":
        if args.calendar_command == "list":
            return connector.calendar_list(time_min=args.time_min or None, time_max=args.time_max or None, max_results=args.max_results)
        if args.calendar_command in {"propose-create", "propose-update"}:
            from .connectors.google_actions import propose_calendar_create, propose_calendar_update

            connector, workflow = _google_calendar_workflow(args)
            if args.calendar_command == "propose-create":
                event = {
                    "summary": args.summary,
                    "start": args.start,
                    "end": args.end,
                    "location": args.location,
                    "description": args.description,
                }
                proposal, review = propose_calendar_create(workflow, connector, event)
            else:
                patch: dict[str, Any] = {}
                for field in ("summary", "start", "end", "location", "description"):
                    value = getattr(args, field)
                    if value is not None:
                        patch[field] = value
                if args.clear_location:
                    patch["location"] = ""
                if args.clear_description:
                    patch["description"] = ""
                proposal, review = propose_calendar_update(connector=connector, workflow=workflow, event_id=args.event_id, patch=patch)
            return {"proposal": asdict(proposal), "review": asdict(review), "next_step": f"academia review decide {review.id} approve_action --json"}
    raise ValueError(f"unsupported Google connector command: {args.google_command}")


def _mcp_connections(args: argparse.Namespace) -> Any:
    from .mcp_connections import MCPConnectionManager
    config = load_config(_profile_path(args))
    manager = MCPConnectionManager(runtime_directory(config) / "mcp_connections.json")
    if args.mcp_connections_command == "list":
        return manager.list()
    if args.mcp_connections_command == "add":
        return manager.add(name=args.name, command=args.connection_command, args=args.connection_args, cwd=args.cwd)
    if args.mcp_connections_command == "add-remote":
        return manager.add_remote(name=args.name, url=args.url)
    if args.mcp_connections_command == "authorize":
        from .native_bridge import run_lease

        started = manager.begin_authorize(args.connection_id)
        if not args.no_open:
            webbrowser.open(started["authorization_url"])
        cancelled = threading.Event()

        def cancel_authorization() -> None:
            cancelled.set()
            try:
                manager.cancel_authorize(args.connection_id)
            except (KeyError, ValueError):
                pass

        deadline = time.monotonic() + 180
        with run_lease(_profile_path(args), "mcp", args.connection_id, cancel_authorization):
            while time.monotonic() < deadline:
                status = manager.oauth_status(args.connection_id)
                if status["auth_status"] in {"authorized", "error"} or cancelled.is_set():
                    return status
                time.sleep(0.5)
        raise ValueError("MCP authorization timed out")
    if args.mcp_connections_command == "oauth-status":
        return manager.oauth_status(args.connection_id)
    if args.mcp_connections_command == "oauth-cancel":
        from .native_bridge import request_cancel

        requested = request_cancel(_profile_path(args), "mcp", args.connection_id)
        if requested["cancelled"]:
            return manager.oauth_status(args.connection_id)
        return manager.cancel_authorize(args.connection_id)
    if args.mcp_connections_command == "trust":
        return manager.trust_remote(args.connection_id)
    if args.mcp_connections_command == "inspect":
        return manager.inspect(args.connection_id)
    if args.mcp_connections_command == "grant":
        return manager.grant(args.connection_id, args.granted_tools)
    if args.mcp_connections_command == "call":
        try:
            arguments = json.loads(args.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("--arguments must be a JSON object") from exc
        if not isinstance(arguments, dict):
            raise ValueError("--arguments must be a JSON object")
        return manager.call_read_tool(args.connection_id, args.tool, arguments)
    if args.mcp_connections_command == "enable":
        return manager.enable(args.connection_id)
    if args.mcp_connections_command == "disable":
        return manager.disable(args.connection_id)
    if args.mcp_connections_command == "disconnect":
        return manager.disconnect(args.connection_id)
    raise ValueError(f"unsupported mcp-connections command: {args.mcp_connections_command}")


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
        if name == "status":
            command.add_argument("--fast", action="store_true", help="Use the local workspace index for a quick desktop first paint")
        if name in {"courses", "tasks"}:
            command.add_argument("--semester", help="Read courses from a specific semester folder")
    task = sub.add_parser("task", help="Create and maintain user tasks in SEMESTER_TASKS.md")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_list = task_sub.add_parser("list", help="Read canonical user tasks and any task-file error")
    task_list.add_argument("--semester", help="Read tasks from a specific semester folder")
    task_list.add_argument("--json", action="store_true")
    task_create = task_sub.add_parser("create", help="Create one user task")
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--course", dest="course_id")
    task_create.add_argument("--due-date", help="Calendar date in YYYY-MM-DD")
    task_create.add_argument("--due-time", help="Local 24-hour time in HH:MM")
    task_create.add_argument("--semester", help="Semester containing SEMESTER_TASKS.md")
    task_create.add_argument("--json", action="store_true")
    task_update = task_sub.add_parser("update", help="Update one user task")
    task_update.add_argument("task_id")
    task_update.add_argument("--title")
    task_update.add_argument("--course", dest="course_id", default=argparse.SUPPRESS)
    task_update.add_argument("--clear-course", action="store_true")
    task_update.add_argument("--due-date", default=argparse.SUPPRESS)
    task_update.add_argument("--clear-due-date", action="store_true")
    task_update.add_argument("--due-time", default=argparse.SUPPRESS)
    task_update.add_argument("--clear-due-time", action="store_true")
    task_update.add_argument("--status", choices=("open", "done", "cancelled"))
    task_update.add_argument("--semester", help="Semester containing SEMESTER_TASKS.md")
    task_update.add_argument("--json", action="store_true")
    for action, summary in (("complete", "Mark one user task done"), ("reopen", "Reopen one completed user task")):
        task_action = task_sub.add_parser(action, help=summary)
        task_action.add_argument("task_id")
        task_action.add_argument("--semester", help="Semester containing SEMESTER_TASKS.md")
        task_action.add_argument("--json", action="store_true")
    process = sub.add_parser("process", help="Manage local background text extraction")
    process_sub = process.add_subparsers(dest="process_command", required=True)
    process_status = process_sub.add_parser("status", help="Show processing records without refreshing source signatures")
    process_status.add_argument("--json", action="store_true")
    process_start = process_sub.add_parser("start", help="Start background extraction for a pending inbox file")
    process_start.add_argument("record_id")
    process_start.add_argument("--json", action="store_true")
    process_batch = process_sub.add_parser("batch", help="Process pending and retry failed inbox files with bounded concurrency")
    process_batch.add_argument("--max-workers", type=int, default=3, help="Maximum simultaneous local extractions (1-3)")
    process_batch.add_argument("--json", action="store_true")
    process_forget = process_sub.add_parser("forget", help="Forget a failed processing record for a missing inbox file")
    process_forget.add_argument("record_id")
    process_forget.add_argument("--json", action="store_true")
    process_run = process_sub.add_parser("run", help=argparse.SUPPRESS)
    process_run.add_argument("record_id")
    process_run.add_argument("--json", action="store_true")
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
    agent_playbooks = agent_sub.add_parser("playbooks", help="List read-only Agent Setup Playbooks")
    agent_playbooks.add_argument("--json", action="store_true")
    agent_playbook = agent_sub.add_parser("playbook", help="Read one read-only Agent Setup Playbook")
    agent_playbook.add_argument("playbook_id")
    agent_playbook.add_argument("--json", action="store_true")
    agent_recommendations = agent_sub.add_parser("recommendations", help="Compatibility alias for `agent playbooks`")
    agent_recommendations.add_argument("--json", action="store_true")
    agent_recipe = agent_sub.add_parser("recipe", help="Compatibility alias for `agent playbook`")
    agent_recipe.add_argument("workflow_id")
    agent_recipe.add_argument("--json", action="store_true")
    assistant = sub.add_parser("assistant", help="Inspect the first-party assistant contract and provider status")
    assistant_sub = assistant.add_subparsers(dest="assistant_command", required=True)
    assistant_tools = assistant_sub.add_parser("tools", help="List read-only assistant tools and their schemas")
    assistant_tools.add_argument("--json", action="store_true")
    assistant_capabilities = assistant_sub.add_parser("capabilities", help="Read the assistant runtime and provider capability status")
    assistant_capabilities.add_argument("--json", action="store_true")
    assistant_run = assistant_sub.add_parser("run", help="Run one read-only request through the verified Codex app-server backend")
    assistant_run.add_argument("--message", required=True)
    assistant_run.add_argument("--course", dest="course_id", help="Optional exact course ID, code, or name")
    assistant_run.add_argument("--model", help="Optional Codex model override")
    assistant_run.add_argument("--proposal-mode", action="store_true", help="Let Codex create Review/Action proposals, never direct writes")
    assistant_run.add_argument("--proposal-tool", action="append", choices=("propose_import", "propose_task", "propose_calendar"), dest="proposal_tools", help="Grant one exact proposal tool in proposal mode; may be repeated")
    assistant_run.add_argument("--json", action="store_true")
    assistant_propose_import = assistant_sub.add_parser("propose-import", help="Create a Review/Action proposal for one local file import")
    assistant_propose_import.add_argument("--source", required=True, help="Exact local source file")
    assistant_propose_import.add_argument("--target", required=True, help="Exact semester or course 00_INBOX id")
    assistant_propose_import.add_argument("--source-label", help="Optional provenance label")
    assistant_propose_import.add_argument("--json", action="store_true")
    assistant_propose_task = assistant_sub.add_parser("propose-task", help="Create a Review/Action proposal for one personal task change")
    assistant_propose_task.add_argument("--action", choices=("create", "update"), required=True)
    assistant_propose_task.add_argument("--task-id")
    assistant_propose_task.add_argument("--title")
    assistant_propose_task.add_argument("--course", dest="course_id")
    assistant_propose_task.add_argument("--due-date")
    assistant_propose_task.add_argument("--due-time")
    assistant_propose_task.add_argument("--evidence-source", required=True)
    assistant_propose_task.add_argument("--evidence-path", required=True)
    assistant_propose_task.add_argument("--source-location")
    assistant_propose_task.add_argument("--confidence", choices=("current-confirmed", "likely", "unverified", "historical"), default="unverified")
    assistant_propose_task.add_argument("--authority", default="unknown")
    assistant_propose_task.add_argument("--semester", help="Semester containing SEMESTER_TASKS.md")
    assistant_propose_task.add_argument("--json", action="store_true")
    workflow = sub.add_parser("workflow", help="Read or save local student workflow preferences")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_preferences = workflow_sub.add_parser("preferences", help="List saved workflow preferences")
    workflow_preferences.add_argument("--json", action="store_true")
    workflow_show = workflow_sub.add_parser("show", help="Show one Agent Setup Playbook and its saved preferences")
    workflow_show.add_argument("workflow_id")
    workflow_show.add_argument("--json", action="store_true")
    workflow_reset = workflow_sub.add_parser("reset", help="Reset one playbook's local preferences to its recommended defaults")
    workflow_reset.add_argument("workflow_id")
    workflow_reset.add_argument("--json", action="store_true")
    workflow_set = workflow_sub.add_parser("set", help="Save local preference overrides for one Agent Setup Playbook")
    workflow_set.add_argument("workflow_id")
    workflow_set.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="Preference override; JSON booleans, numbers, and arrays are accepted")
    workflow_set.add_argument("--preferences-json", help="JSON object of preference overrides")
    workflow_set.add_argument("--replace-preferences", action="store_true", help="Replace the complete structured override set instead of merging it")
    workflow_set.add_argument("--custom-instructions", default=argparse.SUPPRESS)
    workflow_set.add_argument("--external-setup-notes", default=argparse.SUPPRESS)
    workflow_set.add_argument("--updated-by", default="user", help="Audit attribution: user or agent:<name>")
    workflow_set.add_argument("--json", action="store_true")
    semester = sub.add_parser("semester", help="Resolve the current semester using the shared calendar and timezone policy")
    semester.add_argument("--timezone", default="UTC")
    semester.add_argument("--json", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("action", choices=["list", "show", "approve", "reject", "resolve", "decide", "execute", "amend"], nargs="?", default="list")
    review.add_argument("item_id", nargs="?")
    review.add_argument("decision", nargs="?", help="Typed decision such as use_new or choose_course:...")
    review.add_argument("--actor", choices=("user", "agent:mcp"), default="user", help="Audit attribution for a user-authorized review action")
    review.add_argument("--semester", help="Resolve course choices against a specific recognized semester")
    review.add_argument("--pending-execution", action="store_true", help="Include approved action-linked items that still need execution")
    review.add_argument("--task-title", dest="amend_title", help="Amended title for a proposed personal task")
    review.add_argument("--course", dest="amend_course_id", default=argparse.SUPPRESS, help="Amended course for a proposed personal task")
    review.add_argument("--clear-course", action="store_true", help="Clear the course on a proposed personal task")
    review.add_argument("--due-date", dest="amend_due_date", default=argparse.SUPPRESS, help="Amended due date in YYYY-MM-DD")
    review.add_argument("--clear-due-date", action="store_true", help="Clear the due date on a proposed personal task")
    review.add_argument("--due-time", dest="amend_due_time", default=argparse.SUPPRESS, help="Amended local due time in HH:MM")
    review.add_argument("--clear-due-time", action="store_true", help="Clear the due time on a proposed personal task")
    review.add_argument("--json", action="store_true")
    course = sub.add_parser("course")
    course.add_argument("course_id", nargs="?")
    course.add_argument("--json", action="store_true")
    domain = sub.add_parser("domain")
    domain.add_argument("entity_type", choices=ENTITY_TYPES, nargs="?")
    domain.add_argument("--json", action="store_true")
    history = sub.add_parser("history", help="Read or update a course's assignment and project history")
    history_sub = history.add_subparsers(dest="history_command", required=True)
    history_list = history_sub.add_parser("list", help="List coursework records for one course")
    history_list.add_argument("--course", dest="course_id", required=True)
    history_list.add_argument("--semester", help="Semester containing the course; defaults to the active semester")
    history_list.add_argument("--json", action="store_true")
    history_add = history_sub.add_parser("add", help="Add a user-confirmed coursework history record")
    history_add.add_argument("--course", dest="course_id", required=True)
    history_add.add_argument("--semester", help="Semester containing the course; defaults to the active semester")
    history_add.add_argument("--kind", required=True, choices=("assignment", "essay", "project", "exam", "presentation", "quiz", "other"))
    history_add.add_argument("--title", required=True)
    history_add.add_argument("--status", required=True, choices=("planned", "in_progress", "submitted", "graded", "completed"))
    history_add.add_argument("--due-date")
    history_add.add_argument("--submitted-on")
    history_add.add_argument("--grade")
    history_add.add_argument("--task-title", help="Exact course task title to associate with this record")
    history_add.add_argument("--artifact", action="append", dest="artifact_paths", help="Course-relative file path; may be repeated")
    history_add.add_argument("--notes")
    history_add.add_argument("--actor", default="user")
    history_add.add_argument("--json", action="store_true")
    history_update = history_sub.add_parser("update", help="Update a coursework record without deleting its status history")
    history_update.add_argument("--course", dest="course_id", required=True)
    history_update.add_argument("--semester", help="Semester containing the course; defaults to the active semester")
    history_update.add_argument("--id", dest="record_id", required=True)
    history_update.add_argument("--kind", choices=("assignment", "project", "essay", "exam", "presentation", "quiz", "other"))
    history_update.add_argument("--title")
    history_update.add_argument("--status", choices=("planned", "in_progress", "submitted", "graded", "completed"))
    history_update.add_argument("--due-date")
    history_update.add_argument("--submitted-on")
    history_update.add_argument("--grade")
    history_update.add_argument("--task-title")
    history_update.add_argument("--artifact", action="append", dest="artifact_paths")
    history_update.add_argument("--clear-artifacts", action="store_true")
    history_update.add_argument("--notes")
    history_update.add_argument("--actor", default="user")
    history_update.add_argument("--json", action="store_true")
    library = sub.add_parser("library", help="List visible material in the active semester")
    library.add_argument("--category", choices=("all", "syllabi", "readings", "lectures", "assessments", "notes", "other"), default="all")
    library.add_argument("--location", choices=("all", "inbox", "organized"), default="all")
    library.add_argument("--processing-status", choices=("all", "not_processed", "in_progress", "processed", "failed", "untracked"), default="all")
    library.add_argument("--course", dest="course_id")
    library.add_argument("--query", default="")
    library.add_argument("--semester", help="Read material from a specific semester folder")
    library.add_argument("--json", action="store_true")
    file_preview_command = sub.add_parser("file-preview", help="Read a bounded preview of one active-semester Library file")
    file_preview_command.add_argument("source", type=Path)
    file_preview_command.add_argument("--semester", help="Read the file from a specific semester folder")
    file_preview_command.add_argument("--include-image-data", action="store_true", help="Include bounded image bytes for the desktop reader")
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
    imported.add_argument("--actor", choices=("user", "agent:mcp"), default="user", help="Audit attribution for an explicitly requested import")
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
    mcp = sub.add_parser("mcp", help="Expose bounded local Academia tools over MCP stdio")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_sub.add_parser("serve", help="Run an MCP stdio server for an authorized local agent")
    mcp_mode = mcp_serve.add_mutually_exclusive_group()
    mcp_mode.add_argument("--read-only", action="store_true", help="Expose read tools only; disable all write and proposal tools")
    mcp_mode.add_argument("--proposal-only", action="store_true", help="Expose read tools and exact approval proposals, but no direct writes")
    mcp_serve.add_argument("--proposal-tool", action="append", choices=("propose_import", "propose_task", "propose_calendar"), dest="proposal_tools", help="Grant one exact proposal tool in proposal-only mode; may be repeated")
    mcp_serve.add_argument("--semester", help="Limit read tools to one exact semester folder")
    mcp_serve.add_argument("--course", help="Limit read tools to one exact course ID, code, or name")
    connections = sub.add_parser("mcp-connections", help="Manage local external MCP connections and read-only tool grants")
    connections_sub = connections.add_subparsers(dest="mcp_connections_command", required=True)
    connections_list = connections_sub.add_parser("list", help="List local MCP connection records")
    connections_list.add_argument("--json", action="store_true")
    connections_add = connections_sub.add_parser("add", help="Add one local stdio MCP connection")
    connections_add.add_argument("--name", required=True)
    connections_add.add_argument("--command", dest="connection_command", required=True)
    connections_add.add_argument("--arg", action="append", dest="connection_args", default=[])
    connections_add.add_argument("--cwd")
    connections_add.add_argument("--json", action="store_true")
    connections_add_remote = connections_sub.add_parser("add-remote", help="Add one remote streamable-HTTP MCP connection")
    connections_add_remote.add_argument("--name", required=True)
    connections_add_remote.add_argument("--url", required=True)
    connections_add_remote.add_argument("--json", action="store_true")
    connections_authorize = connections_sub.add_parser("authorize", help="Start OAuth and open the verification page")
    connections_authorize.add_argument("connection_id")
    connections_authorize.add_argument("--no-open", action="store_true")
    connections_authorize.add_argument("--json", action="store_true")
    for action, summary in (
        ("oauth-status", "Read the OAuth status for one remote connection"),
        ("oauth-cancel", "Cancel a pending OAuth authorization"),
        ("trust", "Trust one inspected remote server's read-only declarations"),
    ):
        command = connections_sub.add_parser(action, help=summary)
        command.add_argument("connection_id")
        command.add_argument("--json", action="store_true")
    for action, summary in (
        ("inspect", "Start the server once and read its tool list"),
        ("enable", "Enable a connection with read-only tool grants"),
        ("disable", "Disable one connection"),
        ("disconnect", "Remove one connection record"),
    ):
        command = connections_sub.add_parser(action, help=summary)
        command.add_argument("connection_id")
        command.add_argument("--json", action="store_true")
    connections_grant = connections_sub.add_parser("grant", help="Replace the read-only tool grants for one connection")
    connections_grant.add_argument("connection_id")
    connections_grant.add_argument("--tool", action="append", dest="granted_tools", default=[])
    connections_grant.add_argument("--json", action="store_true")
    connections_call = connections_sub.add_parser("call", help="Call one granted read-only tool")
    connections_call.add_argument("connection_id")
    connections_call.add_argument("--tool", required=True)
    connections_call.add_argument("--arguments", default="{}", help="JSON object of tool arguments")
    connections_call.add_argument("--json", action="store_true")
    models = sub.add_parser("models", help="Manage API model providers and model routing")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list", help="List configured model providers and routing preferences")
    models_list.add_argument("--json", action="store_true")
    models_providers = models_sub.add_parser("providers", help="List available provider presets")
    models_providers.add_argument("--json", action="store_true")
    models_add = models_sub.add_parser("add", help="Validate and add an API model provider")
    models_add.add_argument("--input-file", help="JSON object with provider, api_key, base_url, and optional name")
    models_add.add_argument("--provider")
    models_add.add_argument("--api-key")
    models_add.add_argument("--api-key-file")
    models_add.add_argument("--base-url", default="")
    models_add.add_argument("--name", default="")
    models_add.add_argument("--json", action="store_true")
    for action, summary in (
        ("test", "Revalidate a configured provider and refresh its model list"),
        ("remove", "Remove one provider and its local API key"),
        ("enable", "Enable a configured provider for routing"),
        ("disable", "Disable a configured provider without deleting it"),
    ):
        command = models_sub.add_parser(action, help=summary)
        command.add_argument("provider_id")
        command.add_argument("--json", action="store_true")
    models_preferences = models_sub.add_parser("preferences", help="Read per-task model routing")
    models_preferences.add_argument("--json", action="store_true")
    models_set = models_sub.add_parser("set-preferences", help="Set per-task model routing")
    for role in ("default", "fast", "deep", "vision", "image"):
        models_set.add_argument(f"--{role}")
    models_set.add_argument("--json", action="store_true")
    connectors = sub.add_parser("connectors", help="Manage Google Gmail and Calendar connections")
    connectors_sub = connectors.add_subparsers(dest="connector_command", required=True)
    google = connectors_sub.add_parser("google", help="Google account, Gmail, and Calendar")
    google_sub = google.add_subparsers(dest="google_command", required=True)
    google_setup = google_sub.add_parser("setup", help="Import a downloaded Google OAuth Desktop client JSON")
    google_setup.add_argument("--client-json", required=True)
    google_setup.add_argument("--json", action="store_true")
    for action, summary in (
        ("status", "Show the Google connection status"),
        ("authorize", "Open Google consent and store tokens in the system credential store"),
        ("oauth-status", "Read the current Google authorization status"),
        ("oauth-cancel", "Cancel a pending Google authorization"),
        ("disconnect", "Remove the stored Google account tokens"),
    ):
        command = google_sub.add_parser(action, help=summary)
        command.add_argument("--json", action="store_true")
        if action == "authorize":
            command.add_argument("--no-open", action="store_true")
    google_gmail = google_sub.add_parser("gmail", help="Read Gmail messages")
    gmail_sub = google_gmail.add_subparsers(dest="gmail_command", required=True)
    gmail_list = gmail_sub.add_parser("list", help="List recent Gmail messages")
    gmail_list.add_argument("--query", default="")
    gmail_list.add_argument("--max", dest="max_results", type=int, default=10)
    gmail_list.add_argument("--json", action="store_true")
    gmail_get = gmail_sub.add_parser("get", help="Read one Gmail message")
    gmail_get.add_argument("message_id")
    gmail_get.add_argument("--json", action="store_true")
    google_calendar = google_sub.add_parser("calendar", help="Read Google Calendar events")
    calendar_sub = google_calendar.add_subparsers(dest="calendar_command", required=True)
    calendar_list = calendar_sub.add_parser("list", help="List upcoming primary-calendar events")
    calendar_list.add_argument("--time-min", default="")
    calendar_list.add_argument("--time-max", default="")
    calendar_list.add_argument("--max", dest="max_results", type=int, default=20)
    calendar_list.add_argument("--json", action="store_true")
    calendar_create = calendar_sub.add_parser("propose-create", help="Create a calendar event proposal for Review")
    calendar_create.add_argument("--summary", required=True)
    calendar_create.add_argument("--start", required=True, help="RFC 3339 date-time including a timezone offset")
    calendar_create.add_argument("--end", required=True, help="RFC 3339 date-time including a timezone offset")
    calendar_create.add_argument("--location")
    calendar_create.add_argument("--description")
    calendar_create.add_argument("--json", action="store_true")
    calendar_update = calendar_sub.add_parser("propose-update", help="Edit a calendar event through a Review proposal")
    calendar_update.add_argument("event_id")
    calendar_update.add_argument("--summary")
    calendar_update.add_argument("--start", help="RFC 3339 date-time including a timezone offset")
    calendar_update.add_argument("--end", help="RFC 3339 date-time including a timezone offset")
    calendar_update.add_argument("--location")
    calendar_update.add_argument("--clear-location", action="store_true")
    calendar_update.add_argument("--description")
    calendar_update.add_argument("--clear-description", action="store_true")
    calendar_update.add_argument("--json", action="store_true")
    from .study.cli import add_parser as add_study_parser
    add_study_parser(sub)
    dashboard_chat = sub.add_parser("chat", help=argparse.SUPPRESS)
    dashboard_chat.add_argument("--input-file", required=True)
    native_chat = sub.add_parser("chat-stream", help=argparse.SUPPRESS)
    native_chat.add_argument("--input-file", required=True)
    native_chat.add_argument("--run-id", required=True)
    native_chat_cancel = sub.add_parser("chat-cancel", help=argparse.SUPPRESS)
    native_chat_cancel.add_argument("--run-id", required=True)
    native_chat_cancel.add_argument("--json", action="store_true")
    account = sub.add_parser("account", help=argparse.SUPPRESS)
    account_sub = account.add_subparsers(dest="account_command", required=True)
    for action in ("status", "logout"):
        account_command = account_sub.add_parser(action, help=argparse.SUPPRESS)
        account_command.add_argument("--json", action="store_true")
    account_cancel = account_sub.add_parser("login-cancel", help=argparse.SUPPRESS)
    account_cancel.add_argument("--run-id", required=True)
    account_cancel.add_argument("--json", action="store_true")
    account_login = account_sub.add_parser("login-stream", help=argparse.SUPPRESS)
    account_login.add_argument("--run-id", required=True)
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
        if args.command == "mcp":
            from .mcp_server import serve
            if args.proposal_tools and not args.proposal_only:
                raise ValueError("--proposal-tool requires --proposal-only")
            return serve(
                profile=args.profile,
                read_only=bool(args.read_only),
                proposal_only=bool(args.proposal_only),
                proposal_tools={f"academia_{name}" for name in args.proposal_tools} if args.proposal_tools else None,
                semester=args.semester,
                course=args.course,
            )
        if args.command == "status":
            value = _status(args); _emit(value, as_json=args.json, human=_human_status); return 0
        if args.command in {"process", "study", "chat", "chat-stream", "chat-cancel", "account", "models", "connectors", "courses", "today", "tasks", "task", "course", "domain", "history", "library", "file-preview", "extract", "workspace", "review", "inbox", "activity", "agents", "capabilities", "agent", "assistant", "workflow", "semester", "watch", "import", "verify", "verify-source", "settings", "migration", "dashboard", "mcp-connections"}:
            return dispatch(args)
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False))
        else:
            print(f"academia: {exc}", file=sys.stderr)
        return 2
    return 2


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "models":
        _emit(_models(args), as_json=args.json)
        return 0
    if args.command == "connectors":
        _emit(_connectors(args), as_json=args.json)
        return 0
    if args.command == "mcp-connections":
        _emit(_mcp_connections(args), as_json=args.json)
        return 0
    if args.command == "assistant":
        from .assistant import ASSISTANT_CONTRACT_VERSION, CodexAppServerRuntime, ReadContext, RunRequest, Scope, WRITE_TOOL_DESCRIPTORS, descriptors
        if args.assistant_command == "tools":
            value = {
                "contract_version": ASSISTANT_CONTRACT_VERSION,
                "write_tools": [descriptor.as_dict() for descriptor in WRITE_TOOL_DESCRIPTORS],
                "tools": descriptors(),
            }
        elif args.assistant_command == "capabilities":
            codex_path = shutil.which("codex")
            auth_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
            available = bool(codex_path and auth_path.is_file())
            value = {
                "contract_version": ASSISTANT_CONTRACT_VERSION,
                "runtime": {"status": "read_only_default_proposal_only_available", "write_tools": "proposal_only", "provider_required": True},
                "provider_gate": {
                    "status": "read_only_passed" if available else "pending",
                    "requirement": "Direct write tools remain disabled; proposal-only mode creates Review/Action items for human approval.",
                },
                "providers": [{
                    "id": "codex-app-server",
                    "name": "Codex app-server",
                    "available": available,
                    "read_only": True,
                    "writes": False,
                    "proposal_mode": True,
                    "authentication": "Codex-managed ChatGPT sign-in",
                }],
                "write_policy": {
                    "status": "approval_required_for_state_changes",
                    "tools": [descriptor.name for descriptor in WRITE_TOOL_DESCRIPTORS],
                },
                "tool_grants": {
                    "default": "read_only",
                    "allowed_write_tools": [
                        {
                            "name": descriptor.name,
                            "requires_approval": descriptor.requires_approval,
                            "confirmation": "review" if descriptor.requires_approval else "host",
                        }
                        for descriptor in WRITE_TOOL_DESCRIPTORS
                    ],
                },
                "tools": descriptors(),
            }
        elif args.assistant_command == "propose-import":
            from .assistant.tools.write import propose_import
            config = load_config(_profile_path(args))
            context = ReadContext.create(config, hosted_model_allowed=False)
            value = propose_import(
                context,
                source_path=args.source,
                target_id=args.target,
                source_label=args.source_label,
            )
        elif args.assistant_command == "propose-task":
            from .assistant.tools.write import propose_task_change
            config = load_config(_profile_path(args))
            context = ReadContext.create(config, semester=args.semester, hosted_model_allowed=False)
            optional: dict[str, Any] = {}
            if args.due_date is not None:
                optional["due_date"] = args.due_date
            if args.due_time is not None:
                optional["due_time"] = args.due_time
            value = propose_task_change(
                context,
                action=args.action,
                task_id=args.task_id,
                title=args.title,
                course=args.course_id,
                evidence_source=args.evidence_source,
                evidence_path=args.evidence_path,
                source_location=args.source_location,
                confidence=args.confidence,
                authority=args.authority,
                **optional,
            )
        else:
            config = load_config(_profile_path(args))
            root = Path(config["academic"]["root_directory"]).expanduser().resolve()
            course_id = None
            if args.course_id:
                from .workspace import build_workspace_snapshot
                snapshot = build_workspace_snapshot(config, persist=False)
                course = resolve_course_identifier(snapshot.get("courses", []), args.course_id)
                course_id = str(course["id"])
            scope = Scope(
                kind="course",
                semester=config["academic"]["semester"],
                course_id=course_id,
            ) if course_id else Scope()
            model = args.model
            if not model:
                from .study.providers import codex_model, codex_runtime
                model, _notice = codex_model(codex_runtime())
            if args.proposal_tools and not args.proposal_mode:
                raise ValueError("--proposal-tool requires --proposal-mode")
            result = CodexAppServerRuntime(
                academic_root=root,
                profile_path=_profile_path(args),
                model=model,
                mcp_mode="proposal_only" if args.proposal_mode else "read_only",
                proposal_tools=tuple(args.proposal_tools) if args.proposal_tools else None,
            ).run(RunRequest(
                messages=({"role": "user", "content": args.message},),
                scope=scope,
            ))
            _emit(result.as_dict(), as_json=args.json)
            return 0 if result.status == "completed" else 1
        _emit(value, as_json=args.json)
        return 0
    if args.command == "process":
        config = load_config(_profile_path(args))
        if args.process_command == "status":
            from .processing import ProcessingStore
            root = Path(config["academic"]["root_directory"]).expanduser().resolve()
            value = [asdict(record) for record in ProcessingStore(root / ".academia" / "processing.json").list()]
        elif args.process_command == "start":
            from .processing import ProcessingStatus, ProcessingStore
            from .processing_worker import AUTOMATIC_EXTRACTION_EXTENSIONS, launch_processing_worker
            root = Path(config["academic"]["root_directory"]).expanduser().resolve()
            processing = ProcessingStore(root / ".academia" / "processing.json")
            record = processing.get(args.record_id)
            if record.status is not ProcessingStatus.PENDING:
                raise ValueError(f"processing record is {record.status.value.lower()}, not pending")
            if Path(record.source_path).suffix.casefold() not in AUTOMATIC_EXTRACTION_EXTENSIONS:
                raise ValueError("automatic extraction is not available for this file type")
            worker = launch_processing_worker(_profile_path(args), record.id)
            value = {"record_id": record.id, "status": "started", "pid": worker.pid}
        elif args.process_command == "batch":
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from .processing import ProcessingStatus, ProcessingStore
            from .processing_worker import MAX_CONCURRENT_EXTRACTION_WORKERS, AUTOMATIC_EXTRACTION_EXTENSIONS, process_record

            if args.max_workers < 1 or args.max_workers > MAX_CONCURRENT_EXTRACTION_WORKERS:
                raise ValueError(f"--max-workers must be between 1 and {MAX_CONCURRENT_EXTRACTION_WORKERS}")
            root = Path(config["academic"]["root_directory"]).expanduser().resolve()
            processing = ProcessingStore(root / ".academia" / "processing.json")
            all_records = processing.list()
            queue = [
                record for record in all_records
                if record.status in {ProcessingStatus.PENDING, ProcessingStatus.FAILED}
                or (
                    record.status is ProcessingStatus.ACKNOWLEDGED
                    and (record.verification or {}).get("extraction_status") == "unsupported_without_ocr"
                    and Path(record.source_path).suffix.casefold() in AUTOMATIC_EXTRACTION_EXTENSIONS
                )
            ]
            pending: list[Any] = []
            for record in queue:
                if record.status is ProcessingStatus.FAILED:
                    try:
                        record = processing.retry(record.id)
                    except ValueError:
                        continue
                elif record.status is ProcessingStatus.ACKNOWLEDGED:
                    try:
                        record = processing.requeue_unsupported_ocr(record.id)
                    except ValueError:
                        continue
                pending.append(record)
            runnable = [record for record in pending if Path(record.source_path).suffix.casefold() in AUTOMATIC_EXTRACTION_EXTENSIONS]
            final_outcomes: dict[str, dict[str, Any]] = {
                record.id: {
                    "record_id": record.id,
                    "name": Path(record.source_path).name,
                    "status": "unsupported_format",
                    "reason": f"automatic extraction is not available for {Path(record.source_path).suffix or 'this file type'}",
                }
                for record in pending if record not in runnable
            }
            todo = list(runnable)
            attempt_rounds = 0
            for _ in range(3):
                if not todo:
                    break
                attempt_rounds += 1
                retry_ids: set[str] = set()
                with ThreadPoolExecutor(max_workers=args.max_workers, thread_name_prefix="academia-process") as pool:
                    futures = {pool.submit(process_record, root, record.id): record for record in todo}
                    for future in as_completed(futures):
                        record = futures[future]
                        try:
                            result = future.result()
                            result.setdefault("name", Path(record.source_path).name)
                            result.setdefault("status", "processed")
                            final_outcomes[record.id] = result
                            if result["status"] == "requeued":
                                retry_ids.add(record.id)
                        except Exception as exc:
                            try:
                                current = processing.get(record.id)
                                status = current.status.value.lower()
                                reason = current.failure_reason or str(exc)
                                # A lifecycle collision that leaves the record
                                # queued is transient; give it another bounded
                                # attempt after the active worker releases its slot.
                                if current.status is ProcessingStatus.PENDING:
                                    status = "requeued"
                                    retry_ids.add(record.id)
                            except (KeyError, OSError):
                                status, reason = "unknown", str(exc)
                            final_outcomes[record.id] = {
                                "record_id": record.id,
                                "name": Path(record.source_path).name,
                                "status": status,
                                "reason": reason[:500],
                            }
                todo = []
                for record_id in retry_ids:
                    try:
                        current = processing.get(record_id)
                    except (KeyError, OSError):
                        continue
                    if current.status is ProcessingStatus.PENDING:
                        todo.append(current)
            outcomes = list(final_outcomes.values())
            counts: dict[str, int] = {}
            for outcome in outcomes:
                state = str(outcome.get("status", "unknown"))
                counts[state] = counts.get(state, 0) + 1
            value = {
                "status": "complete",
                "max_workers": args.max_workers,
                "already_in_progress": sum(record.status is ProcessingStatus.PROCESSING for record in all_records),
                "queued": len(runnable),
                "attempt_rounds": attempt_rounds,
                "unsupported": len(pending) - len(runnable),
                "counts": counts,
                "outcomes": outcomes,
            }
        elif args.process_command == "run":
            from .processing_worker import process_record
            value = process_record(Path(config["academic"]["root_directory"]), args.record_id)
        elif args.process_command == "forget":
            from .processing import ProcessingStore
            root = Path(config["academic"]["root_directory"]).expanduser().resolve()
            processing = ProcessingStore(root / ".academia" / "processing.json")
            record = processing.forget_missing_failed(args.record_id, workspace_root=root)
            ActivityLog(root / ".academia" / "activity.jsonl").append(
                event_type="processing.forgotten",
                title=f"Forgot failed processing record for missing source: {Path(record.source_path).name}",
                details={"record_id": record.id, "previous_status": record.status.value, "failure_reason": record.failure_reason},
                source=record.source_path,
                actor="user",
            )
            value = {"record_id": record.id, "status": "forgotten", "previous_status": record.status.value, "source_path": record.source_path}
        else:
            raise ValueError("unsupported process command")
        _emit(value, as_json=args.json)
        return 0
    if args.command == "task":
        config = load_config(_profile_path(args))
        root = Path(config["academic"]["root_directory"]).expanduser().resolve()
        semester = args.semester or config["academic"]["semester"]
        if not (root / semester).is_dir():
            raise ValueError(f"semester folder does not exist: {semester}")
        store = TaskStore(root, semester)
        if args.task_command == "list":
            try:
                value = {
                    "semester": semester,
                    "path": str(store.path),
                    "tasks": [project_task(task, semester) for task in store.list() if task["status"] != "cancelled"],
                    "task_state_error": None,
                }
            except TaskStateError as exc:
                value = {"semester": semester, "path": str(store.path), "tasks": [], "task_state_error": str(exc)}
        elif args.task_command == "create":
            value = store.create(
                title=args.title,
                course_id=args.course_id,
                due_date=args.due_date,
                due_time=args.due_time,
                actor="user",
            )
        elif args.task_command == "update":
            fields: dict[str, Any] = {}
            if args.title is not None:
                fields["title"] = args.title
            if args.clear_course:
                fields["course_id"] = None
            elif hasattr(args, "course_id"):
                fields["course_id"] = args.course_id
            if args.clear_due_date:
                fields["due_date"] = None
            elif hasattr(args, "due_date"):
                fields["due_date"] = args.due_date
            if args.clear_due_time:
                fields["due_time"] = None
            elif hasattr(args, "due_time"):
                fields["due_time"] = args.due_time
            if args.status is not None:
                fields["status"] = args.status
            if not fields:
                raise ValueError("provide at least one task field to update")
            value = store.update(args.task_id, actor="user", **fields)
        elif args.task_command == "complete":
            value = store.complete(args.task_id, actor="user")
        elif args.task_command == "reopen":
            value = store.reopen(args.task_id, actor="user")
        else:
            raise ValueError(f"unsupported task command: {args.task_command}")
        _emit(value, as_json=args.json)
        return 0
    if args.command == "study":
        from .study.cli import dispatch as dispatch_study
        _emit(dispatch_study(args, _profile_path(args)), as_json=args.json)
        return 0
    if args.command == "chat":
        try:
            payload = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
            from .dashboard_chat import respond
            _emit(respond(payload, profile=_profile_path(args)), as_json=True)
            return 0
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _emit({"error": str(exc)}, as_json=True)
            return 2
    if args.command == "chat-stream":
        from .native_bridge import stream_chat

        def emit(value: dict[str, Any]) -> None:
            print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

        try:
            payload = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            emit({"type": "error", "message": f"Chat request could not be read: {exc}"})
            return 2
        stream_chat(payload, profile=_profile_path(args), run_id=args.run_id, emit=emit)
        return 0
    if args.command == "chat-cancel":
        from .native_bridge import request_cancel
        _emit(request_cancel(_profile_path(args), "chat", args.run_id), as_json=args.json)
        return 0
    if args.command == "account":
        from .native_bridge import account_logout, account_status, request_cancel, stream_account_login

        if args.account_command == "status":
            _emit(account_status(_profile_path(args)), as_json=args.json)
            return 0
        if args.account_command == "logout":
            _emit(account_logout(_profile_path(args)), as_json=args.json)
            return 0
        if args.account_command == "login-cancel":
            _emit(request_cancel(_profile_path(args), "account", args.run_id), as_json=args.json)
            return 0
        if args.account_command == "login-stream":
            def emit_account(value: dict[str, Any]) -> None:
                print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)

            stream_account_login(profile=_profile_path(args), run_id=args.run_id, emit=emit_account)
            return 0
        raise ValueError(f"unsupported account command: {args.account_command}")
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
        if args.agent_command == "playbooks":
            _emit(list_playbooks(), as_json=args.json)
            return 0
        if args.agent_command == "playbook":
            _emit(get_playbook(args.playbook_id), as_json=args.json)
            return 0
        if args.agent_command == "recommendations":
            _emit(list_recommendations(), as_json=args.json)
            return 0
        if args.agent_command == "recipe":
            _emit(get_recipe(args.workflow_id), as_json=args.json)
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
    if args.command == "workflow":
        _emit(_workflow_preferences(args), as_json=args.json)
        return 0
    if args.command == "semester":
        _emit({"semester": resolve_current_semester(timezone_name=args.timezone), "timezone": args.timezone}, as_json=args.json)
        return 0
    if args.command == "courses":
        _, snapshot, _ = _semester_context(args); _emit(snapshot["courses"], as_json=args.json); return 0
    if args.command == "today":
        _, snapshot, _ = _context(args); _emit(snapshot["today"], as_json=args.json); return 0
    if args.command == "tasks":
        _, snapshot, _ = _semester_context(args); _emit(_coursework_tasks(snapshot), as_json=args.json); return 0
    if args.command == "course":
        _, snapshot, _ = _context(args)
        if not args.course_id:
            _emit(snapshot["courses"], as_json=args.json); return 0
        _emit(resolve_course_identifier(snapshot["courses"], args.course_id), as_json=args.json); return 0
    if args.command == "domain":
        _, snapshot, _ = _context(args)
        projection = DomainProjection(Path(snapshot["academic_root"]) / ".academia" / "domain.json")
        _emit(projection.list(args.entity_type), as_json=args.json); return 0
    if args.command == "history":
        _, snapshot, _ = _semester_context(args)
        root = Path(snapshot["academic_root"]).expanduser().resolve()
        semester = args.semester or snapshot["semester"]
        if args.history_command == "list":
            value = list_assignment_history(root, semester, args.course_id)
        elif args.history_command == "add":
            fields = {"kind": args.kind, "title": args.title, "status": args.status}
            for source, target in (("due_date", "due_date"), ("submitted_on", "submitted_on"), ("grade", "grade"), ("task_title", "task_title"), ("artifact_paths", "artifact_paths"), ("notes", "notes")):
                raw = getattr(args, source)
                if raw is not None:
                    fields[target] = raw
            value = add_assignment_history(root, semester, args.course_id, fields, actor=args.actor)
            ActivityLog(root / ".academia" / "activity.jsonl").append(
                event_type="coursework.history_added",
                title=f"Recorded {value['title']} as {value['status'].replace('_', ' ')}",
                course=value["course_id"],
                source=f"{semester}/{value['course_id']}/03_ASSIGNMENTS/Assignment_History.json",
                confidence="user-confirmed",
                details={"record_id": value["id"], "kind": value["kind"], "status": value["status"]},
                actor=args.actor,
            )
        elif args.history_command == "update":
            fields = {}
            for source in ("kind", "title", "status", "due_date", "submitted_on", "grade", "task_title", "artifact_paths", "notes"):
                raw = getattr(args, source)
                if raw is not None:
                    fields[source] = raw
            if args.clear_artifacts:
                fields["artifact_paths"] = []
            value = update_assignment_history(root, semester, args.course_id, args.record_id, fields, actor=args.actor)
            ActivityLog(root / ".academia" / "activity.jsonl").append(
                event_type="coursework.history_updated",
                title=f"Updated {value['title']} history",
                course=value["course_id"],
                source=f"{semester}/{value['course_id']}/03_ASSIGNMENTS/Assignment_History.json",
                confidence="user-confirmed",
                details={"record_id": value["id"], "kind": value["kind"], "status": value["status"]},
                actor=args.actor,
            )
        else:
            raise ValueError(f"unsupported history command: {args.history_command}")
        _emit(value, as_json=args.json); return 0
    if args.command == "library":
        _, snapshot, _ = _semester_context(args)
        items = list_material(Path(snapshot["academic_root"]), snapshot["semester"])
        _emit(filter_material(items, category=args.category, location=args.location, processing_status=args.processing_status, course_id=args.course_id, query=args.query), as_json=args.json); return 0
    if args.command == "file-preview":
        _, snapshot, _ = _semester_context(args)
        value = preview_file(args.source, workspace_root=Path(snapshot["academic_root"]), semester=snapshot["semester"], include_image_data=args.include_image_data)
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
        config, snapshot, profile_path = _semester_context(args)
        state_root = Path(snapshot["academic_root"]) / ".academia"
        queue = ReviewQueue(state_root / "review.json")
        if args.action == "show":
            if not args.item_id:
                raise ValueError("review show requires a review item id")
            review_item = queue.get(args.item_id)
            details = review_item.details if isinstance(review_item.details, dict) else {}
            proposal_details = details.get("proposal_details") if isinstance(details.get("proposal_details"), dict) else {}
            action_status = None
            if review_item.action_proposal_id:
                try:
                    action_status = ActionStore(state_root / "actions.json").get(review_item.action_proposal_id).status
                except KeyError:
                    action_status = None
            value = {
                "id": review_item.id,
                "kind": review_item.kind,
                "title": _sanitize_value(review_item.title, Path(snapshot["academic_root"])),
                "course": _sanitize_value(review_item.course, Path(snapshot["academic_root"])),
                "status": review_item.status.value,
                "action_status": action_status,
                "action_proposal_id": review_item.action_proposal_id,
                "action_type": _sanitize_value(details.get("action_type") or proposal_details.get("action_type"), Path(snapshot["academic_root"]), key="action_type"),
                "details": _sanitize_value(details, Path(snapshot["academic_root"])),
                "created_at": review_item.created_at,
                "updated_at": review_item.updated_at,
            }
            _emit(value, as_json=args.json)
            return 0
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
                value = asdict(workflow.decide_review(args.item_id, args.decision, actor=args.actor))
            elif args.action == "execute":
                review_item = queue.get(args.item_id)
                if not review_item.action_proposal_id:
                    raise ValueError("review execute requires an action-linked Review item")
                details = review_item.details if isinstance(review_item.details, dict) else {}
                proposal_details = details.get("proposal_details") if isinstance(details.get("proposal_details"), dict) else {}
                action_type = details.get("action_type") or proposal_details.get("action_type")
                if action_type == "domain_change":
                    from .extraction.reconcile import execute_domain_change
                    projection = DomainProjection(state_root / "domain.json")
                    value = asdict(workflow.execute_approved(review_item.action_proposal_id, lambda proposal: execute_domain_change(proposal, projection), actor=args.actor if args.actor != "user" else "system"))
                elif action_type == "file_copy":
                    from .assistant.tools.write import execute_import_proposal
                    from .processing import ProcessingStore
                    processing = ProcessingStore(state_root / "processing.json")
                    value = asdict(workflow.execute_approved(
                        review_item.action_proposal_id,
                        lambda proposal: execute_import_proposal(proposal, workspace_root=Path(snapshot["academic_root"]), processing=processing),
                        actor=args.actor if args.actor != "user" else "system",
                    ))
                elif action_type == "task_change":
                    from .assistant.tools.write import execute_task_change
                    value = asdict(workflow.execute_approved(
                        review_item.action_proposal_id,
                        lambda proposal: execute_task_change(proposal, workspace_root=Path(snapshot["academic_root"])),
                        actor=args.actor if args.actor != "user" else "system",
                    ))
                elif action_type == "calendar_change":
                    from .connectors.google import GoogleConnector
                    from .connectors.google_actions import execute_calendar_change
                    connector = GoogleConnector(runtime_directory(config) / "google_connector.json")
                    value = asdict(workflow.execute_approved(
                        review_item.action_proposal_id,
                        lambda proposal: execute_calendar_change(proposal, connector),
                        actor=args.actor if args.actor != "user" else "system",
                    ))
                else:
                    raise ValueError(f"no supported executor for approved action type: {action_type}")
            elif args.action == "amend":
                from .assistant.tools.write import amend_task_proposal
                fields: dict[str, Any] = {}
                if args.amend_title is not None:
                    fields["title"] = args.amend_title
                if args.clear_course:
                    fields["course_id"] = None
                elif hasattr(args, "amend_course_id"):
                    fields["course_id"] = args.amend_course_id
                if args.clear_due_date:
                    fields["due_date"] = None
                elif hasattr(args, "amend_due_date"):
                    fields["due_date"] = args.amend_due_date
                if args.clear_due_time:
                    fields["due_time"] = None
                elif hasattr(args, "amend_due_time"):
                    fields["due_time"] = args.amend_due_time
                if not fields:
                    raise ValueError("review amend requires at least one task field")
                value = asdict(amend_task_proposal(args.item_id, workspace_root=Path(snapshot["academic_root"]), actor=args.actor, **fields))
            elif args.action == "approve":
                value = asdict(workflow.approve_review(args.item_id, actor=args.actor))
            elif args.action == "reject":
                value = asdict(workflow.reject_review(args.item_id, actor=args.actor))
            else:
                value = asdict(workflow.resolve_review(args.item_id))
        else:
            items = queue.list(include_resolved=bool(args.pending_execution))
            if args.pending_execution:
                items = [item for item in items if item.status.value in {"open", "approved"}]
            value = [asdict(item) for item in items]
        _emit(value, as_json=args.json); return 0
    if args.command == "inbox":
        _, snapshot, _ = _context(args)
        from .processing import ProcessingStatus, ProcessingStore, cache_signature, source_signature
        from .state import JsonStateStore
        workspace_root = Path(snapshot["academic_root"])
        processing = ProcessingStore(workspace_root / ".academia" / "processing.json")
        cache_state = JsonStateStore(workspace_root / ".academia" / "extracted_sources.json").read({"records": {}})
        cache_records = cache_state.get("records", {}) if isinstance(cache_state, dict) else {}
        restored_count = 0
        for item in list_material(workspace_root, snapshot["semester"]):
            if item.get("intake_status") != "inbox":
                continue
            source = Path(str(item["path"]))
            try:
                signature = source_signature(source)
            except OSError:
                continue
            record = processing.detect(source, signature=signature)
            relative_key = source.relative_to(workspace_root).as_posix()
            cached = cache_records.get(relative_key) if isinstance(cache_records, dict) else None
            document = cached.get("document") if isinstance(cached, dict) else None
            if not isinstance(cached, dict) or not isinstance(document, dict) or str(document.get("status", "")).casefold() == "failed":
                continue
            try:
                cache_matches = cached.get("signature") == cache_signature(source)
            except OSError:
                cache_matches = False
            if not cache_matches or record.status is ProcessingStatus.ACKNOWLEDGED:
                continue
            restored = processing.restore_acknowledged(
                record.id,
                signature=signature,
                verification={
                    "source_signature": signature,
                    "content_hash": document.get("content_hash"),
                    "extraction_status": document.get("status"),
                    "extraction_method": document.get("extraction_method"),
                    "segment_count": len(document.get("segments", [])) if isinstance(document.get("segments"), list) else 0,
                    "warning_count": len(document.get("warnings", [])) if isinstance(document.get("warnings"), list) else 0,
                    "cache_key": relative_key,
                },
            )
            if restored.status is ProcessingStatus.ACKNOWLEDGED and restored.verification and restored.verification.get("recovered_from_cache"):
                restored_count += 1
        if restored_count:
            ActivityLog(workspace_root / ".academia" / "activity.jsonl").append(
                event_type="processing.state_restored",
                title=f"Restored completed processing status for {restored_count} cached source(s)",
                details={"status": ProcessingStatus.ACKNOWLEDGED.value, "restored_count": restored_count},
                confidence="verified",
                actor="academia:local-index",
            )
        value = [asdict(item) for item in processing.pending()]
        _emit(value, as_json=args.json); return 0
    if args.command == "activity":
        _, snapshot, _ = _context(args)
        # The dashboard applies its own recent/archive retention view. Return a
        # larger bounded window than the general CLI default so resolved events
        # remain available to that view after the recent list grows past 100.
        value = [asdict(item) for item in ActivityLog(Path(snapshot["academic_root"]) / ".academia" / "activity.jsonl").list(limit=1000)]
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
            event_type="file.duplicate_skipped" if value.get("duplicate") else "file.imported",
            title=f"Skipped duplicate {Path(value['destination']).name}" if value.get("duplicate") else f"Imported {Path(value['destination']).name}",
            details=value,
            source=value.get("source_label", str(args.source.expanduser().resolve())),
            confidence="unverified",
            actor=args.actor,
        )
        from .processing_worker import AUTOMATIC_EXTRACTION_EXTENSIONS, launch_processing_worker
        if (
            Path(value["destination"]).suffix.casefold() in AUTOMATIC_EXTRACTION_EXTENSIONS
            and value.get("processing_status") == "PENDING"
        ):
            try:
                worker = launch_processing_worker(_profile_path(args), str(value["processing_record_id"]))
                value["processing_worker"] = {"status": "started", "pid": worker.pid}
            except OSError as exc:
                record = processing.get(str(value["processing_record_id"]))
                if record.status.value == "PENDING":
                    processing.begin(record.id)
                    processing.fail(record.id, f"Could not start local processing worker: {exc}")
                value["processing_worker"] = {"status": "failed_to_start", "reason": str(exc)}
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
