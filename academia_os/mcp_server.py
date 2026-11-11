"""Local MCP stdio server backed by Academia's stable JSON CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
from typing import Any

from .assistant import ReadContext, invoke as invoke_assistant_tool
from .config import load_config
from .version import __version__

_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_PROTOCOL_VERSION = "2024-11-05"
_WRITE_TOOL_NAMES = frozenset({"academia_review_decide", "academia_review_execute", "academia_import_file"})


def _tools_for_mode(read_only: bool) -> list[dict[str, Any]]:
    return [tool for tool in _TOOLS if not read_only or tool["name"] not in _WRITE_TOOL_NAMES]


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }
    if annotations:
        value["annotations"] = annotations
    return value


_TOOLS = [
    _tool("academia_status", "Read the configured local Academia workspace status."),
    _tool("academia_capabilities", "Read the capabilities and safety boundaries implemented by this Academia installation."),
    _tool(
        "academia_courses",
        "List recognized courses in the active semester.",
        {"semester": {"type": "string", "description": "Optional exact semester folder name."}},
    ),
    _tool("academia_today", "Read today's local academic context."),
    _tool(
        "academia_tasks",
        "List academic tasks from the active or named semester.",
        {"semester": {"type": "string", "description": "Optional exact semester folder name."}},
    ),
    _tool(
        "academia_agent_context",
        "Read bounded structured context from the configured local workspace.",
        {
            "scope": {"type": "string", "enum": ["workspace", "semester", "course", "today"]},
            "course": {"type": "string", "description": "Exact course ID, code, or name for course scope."},
            "semester": {"type": "string", "description": "Optional exact semester folder name."},
            "detail": {"type": "string", "enum": ["compact", "standard", "deep"]},
        },
    ),
    _tool(
        "academia_attention",
        "List unresolved review decisions and retryable local issues. This is read-only.",
        {
            "course": {"type": "string", "description": "Optional exact course ID, code, or name."},
            "semester": {"type": "string", "description": "Optional exact semester folder name."},
            "detail": {"type": "string", "enum": ["compact", "standard", "deep"]},
        },
    ),
    _tool(
        "academia_review_item",
        "Read one exact Review item by id. Open items return bounded, sanitized attention details; non-open items return a minimal status summary.",
        {
            "review_id": {"type": "string", "description": "Exact Review id from academia_attention."},
            "semester": {"type": "string", "description": "Optional exact semester used when the Review item was listed."},
        },
        ["review_id"],
        annotations={"readOnlyHint": True, "openWorldHint": False},
    ),
    _tool(
        "academia_review_decide",
        "Record one exact executable choice returned for this Review item. The host must first show the exact choice and its effect and obtain the student's explicit confirmation. The server cannot verify that a confirmation UI was shown. This records approval or rejection only; execution, when supported, is a separate call.",
        {
            "review_id": {"type": "string", "description": "Exact Review id from academia_attention."},
            "decision": {"type": "string", "description": "Exact executable choice id returned for that Review item."},
            "semester": {"type": "string", "description": "Optional exact semester used when the Review item was listed."},
        },
        ["review_id", "decision"],
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    ),
    _tool(
        "academia_review_execute",
        "Execute a previously approved, supported Review action only after the student authorized that exact action and the Review item is approved. The host must not infer approval from a recommendation. Academia currently executes only verified domain-change actions through this path.",
        {
            "review_id": {"type": "string", "description": "Exact approved Review id whose executable choice advertised a separate review_execute step."},
            "semester": {"type": "string", "description": "Optional exact semester containing the linked course."},
        },
        ["review_id"],
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    ),
    _tool(
        "academia_activity_changes",
        "Read append-only Activity events after an optional event ID or timestamp cursor.",
        {
            "since": {"type": "string", "description": "Optional previous event ID or ISO timestamp."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
    ),
    _tool(
        "academia_library",
        "List up to 100 bounded Library records by course, document type, inbox location, processing status, or search text. Returns metadata, not file bodies.",
        {
            "semester": {"type": "string", "description": "Optional exact semester folder name."},
            "course": {"type": "string", "description": "Optional exact course ID, code, or name."},
            "category": {"type": "string", "enum": ["all", "syllabi", "readings", "lectures", "assessments", "notes", "other"]},
            "location": {"type": "string", "enum": ["all", "inbox", "organized"]},
            "processing_status": {"type": "string", "enum": ["all", "not_processed", "in_progress", "processed", "failed", "untracked"]},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
    _tool(
        "academia_read_library_item",
        "Read a bounded preview of a file that appears in Academia's Library. Use its exact id from academia_library.",
        {
            "id": {"type": "string", "description": "Exact Library item id returned by academia_library."},
            "semester": {"type": "string", "description": "Optional exact semester folder name."},
        },
        ["id"],
    ),
    _tool(
        "academia_processing_status",
        "Read local extraction status for imported files.",
    ),
    _tool(
        "academia_import_targets",
        "List valid direct semester and course inboxes. Use the returned exact id when importing.",
        {"semester": {"type": "string", "description": "Optional exact semester folder name; defaults to the active semester."}},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    ),
    _tool(
        "academia_import_file",
        "Copy one exact local file into a target returned by academia_import_targets and start local processing when supported. Ask the student to confirm this file and destination before calling. The original file is preserved; this tool does not access or change the school portal.",
        {
            "source_path": {"type": "string", "description": "Exact local path of the already-downloaded file."},
            "target_id": {"type": "string", "description": "Exact workspace-relative target id returned by academia_import_targets."},
            "source_url": {"type": "string", "description": "Optional source page URL for provenance; query strings and fragments are removed."},
        },
        ["source_path", "target_id"],
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    ),
]

# Read tools are side-effect free. Advertise the standard MCP read-only hint so
# compatible hosts do not need a write-style approval prompt for local reads.
for _tool_definition in _TOOLS:
    if _tool_definition["name"] not in _WRITE_TOOL_NAMES:
        _tool_definition.setdefault("annotations", {})
        _tool_definition["annotations"].update({"readOnlyHint": True, "openWorldHint": False})


class McpError(Exception):
    def __init__(self, message: str, code: int = -32602) -> None:
        super().__init__(message)
        self.code = code


def _cli_prefix(profile: Path | None) -> list[str]:
    args: list[str]
    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        args = [sys.executable, "-m", "academia_os.cli"]
    if profile is not None:
        args.extend(["--profile", str(profile.expanduser().resolve())])
    return args


def _profile_path(profile: Path | None) -> Path:
    if profile is not None:
        return Path(profile).expanduser().resolve()
    return Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser().resolve()


def _read_tool(profile: Path | None, semester: str | None, name: str, arguments: dict[str, Any]) -> Any:
    config = load_config(_profile_path(profile))
    context = ReadContext.create(config, semester=semester or None)
    return invoke_assistant_tool(name, arguments, context)


def _run_cli(args: list[str], profile: Path | None, *, input_text: str | None = None) -> Any:
    command = [*_cli_prefix(profile), *args, "--json"]
    completed = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode:
        message = completed.stdout.strip() or completed.stderr.strip() or "Academia command failed."
        raise McpError(message, -32000)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise McpError("Academia returned invalid JSON to the MCP bridge.", -32000) from exc


def _import_targets(profile: Path | None, semester: str | None = None) -> dict[str, Any]:
    status = _run_cli(["status"], profile)
    workspace = status.get("workspace", {}) if isinstance(status, dict) else {}
    root_value = workspace.get("academic_root") if isinstance(workspace, dict) else None
    active_semester = workspace.get("semester") if isinstance(workspace, dict) else None
    available = workspace.get("available_semesters", []) if isinstance(workspace, dict) else []
    selected_semester = semester or active_semester
    if not isinstance(root_value, str) or not root_value or not isinstance(selected_semester, str) or not selected_semester:
        raise McpError("Academia has no configured workspace semester.", -32000)
    if selected_semester != active_semester and selected_semester not in available:
        raise McpError(f"Unknown workspace semester: {selected_semester}")
    root = Path(root_value).expanduser().resolve()
    semester_root = root / selected_semester
    targets: list[dict[str, Any]] = []
    if semester_root.is_dir():
        relative = Path(selected_semester) / "00_INBOX"
        targets.append({"id": relative.as_posix(), "kind": "semester_inbox", "semester": selected_semester, "course_id": None})
    courses = _run_cli(["courses", "--semester", selected_semester], profile)
    if not isinstance(courses, list):
        raise McpError("Academia returned an invalid course list.", -32000)
    for course in courses:
        if not isinstance(course, dict):
            continue
        course_id = course.get("id")
        if not isinstance(course_id, str) or not course_id or Path(course_id).name != course_id:
            continue
        course_root = semester_root / course_id
        if not course_root.is_dir() or not (course_root / "01_COURSE").is_dir():
            continue
        relative = Path(selected_semester) / course_id / "00_INBOX"
        targets.append({"id": relative.as_posix(), "kind": "course_inbox", "semester": selected_semester, "course_id": course_id, "course_name": course.get("name")})
    return {"semester": selected_semester, "targets": targets}


def _source_url_label(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 4096:
        raise McpError("source_url must be a valid HTTP(S) URL under 4096 characters.")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise McpError("source_url must be an HTTP(S) URL without embedded credentials.")
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return f"browser-upload:{safe_url}"


def _optional(args: list[str], flag: str, value: Any) -> None:
    if value is not None and value != "":
        args.extend([flag, str(value)])


def _call_tool(name: str, values: Any, profile: Path | None, *, read_only: bool = False) -> Any:
    if not isinstance(values, dict):
        raise McpError("Tool arguments must be a JSON object.")
    allowed = {item["name"] for item in _tools_for_mode(read_only)}
    if name not in allowed:
        if read_only and name in _WRITE_TOOL_NAMES:
            raise McpError(f"Tool is disabled in read-only mode: {name}")
        raise McpError(f"Unknown Academia MCP tool: {name}")

    if name == "academia_status":
        return _run_cli(["status"], profile)
    if name == "academia_capabilities":
        return _run_cli(["agent", "capabilities"], profile)
    if name == "academia_courses":
        return _read_tool(profile, values.get("semester"), "course.list", {}).data
    if name == "academia_today":
        return _run_cli(["today"], profile)
    if name == "academia_tasks":
        return _read_tool(profile, values.get("semester"), "task.list", {}).data
    if name == "academia_agent_context":
        scope = values.get("scope", "workspace")
        detail = values.get("detail", "standard")
        if scope not in {"workspace", "semester", "course", "today"} or detail not in {"compact", "standard", "deep"}:
            raise McpError("Use a supported context scope and detail level.")
        if scope == "course" and not values.get("course"):
            raise McpError("Course scope requires an exact course identifier.")
        arguments = {"scope": scope, "detail": detail}
        if values.get("course"):
            arguments["course"] = values["course"]
        return _read_tool(profile, values.get("semester"), "context.get", arguments).data
    if name == "academia_attention":
        detail = values.get("detail", "standard")
        if detail not in {"compact", "standard", "deep"}:
            raise McpError("Use compact, standard, or deep detail.")
        args = ["agent", "attention", "--detail", detail]
        _optional(args, "--course", values.get("course"))
        _optional(args, "--semester", values.get("semester"))
        return _run_cli(args, profile)
    if name == "academia_review_item":
        review_id = values.get("review_id")
        if not isinstance(review_id, str) or not review_id.strip():
            raise McpError("Provide an exact review_id.")
        args = ["agent", "attention", "--detail", "deep"]
        _optional(args, "--semester", values.get("semester"))
        attention = _run_cli(args, profile)
        attention_items = attention.get("items", []) if isinstance(attention, dict) else []
        selected = next((entry for entry in attention_items if isinstance(entry, dict) and entry.get("id") == review_id), None)
        show_args = ["review", "show", review_id]
        _optional(show_args, "--semester", values.get("semester"))
        return selected if selected is not None else _run_cli(show_args, profile)
    if name == "academia_review_decide":
        review_id = values.get("review_id")
        decision = values.get("decision")
        if not isinstance(review_id, str) or not review_id.strip() or not isinstance(decision, str) or not decision.strip():
            raise McpError("Provide an exact review_id and decision.")
        attention_args = ["agent", "attention", "--detail", "deep"]
        _optional(attention_args, "--semester", values.get("semester"))
        attention = _run_cli(attention_args, profile)
        attention_items = attention.get("items", []) if isinstance(attention, dict) else []
        item = next((entry for entry in attention_items if isinstance(entry, dict) and entry.get("id") == review_id), None)
        if item is None:
            raise McpError("Review item is not open or is not present in current Academia attention.")
        selected = next((choice for choice in item.get("choices", []) if isinstance(choice, dict) and choice.get("id") == decision and choice.get("executable") is True), None)
        action = selected.get("action") if isinstance(selected, dict) else None
        if not isinstance(action, dict) or action.get("type") != "review_decision" or action.get("review_id") != review_id or action.get("decision") != decision:
            raise McpError("decision must exactly match an executable Review choice returned by academia_attention.")
        decide_args = ["review", "decide", review_id, decision, "--actor", "agent:mcp"]
        _optional(decide_args, "--semester", values.get("semester"))
        result = _run_cli(decide_args, profile)
        status = result.get("status") if isinstance(result, dict) else None
        return {"review_id": review_id, "status": status, "decision": decision, "requires_execution": bool(action.get("requires_execution")), "execution": action.get("execution")}
    if name == "academia_review_execute":
        review_id = values.get("review_id")
        if not isinstance(review_id, str) or not review_id.strip():
            raise McpError("Provide an exact review_id.")
        show_args = ["review", "show", review_id]
        _optional(show_args, "--semester", values.get("semester"))
        review = _run_cli(show_args, profile)
        if not isinstance(review, dict) or review.get("status") != "approved" or not review.get("action_proposal_id"):
            raise McpError("Only a Review item with a linked action that is already approved can be executed.")
        details = review.get("details") if isinstance(review.get("details"), dict) else {}
        proposal_details = details.get("proposal_details") if isinstance(details.get("proposal_details"), dict) else {}
        action_type = details.get("action_type") or proposal_details.get("action_type")
        if action_type != "domain_change":
            raise McpError("No supported Academia executor exists for this approved action type.")
        execute_args = ["review", "execute", review_id, "--actor", "agent:mcp"]
        _optional(execute_args, "--semester", values.get("semester"))
        result = _run_cli(execute_args, profile)
        return {
            "review_id": review_id,
            "proposal_id": result.get("id") if isinstance(result, dict) else None,
            "status": result.get("status") if isinstance(result, dict) else None,
            "verified": isinstance(result, dict) and result.get("status") == "verified",
        }
    if name == "academia_activity_changes":
        limit = values.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise McpError("Activity limit must be an integer from 1 to 500.")
        arguments = {"limit": limit}
        if values.get("since"):
            arguments["since"] = values["since"]
        return _read_tool(profile, None, "activity.changes", arguments).data
    if name == "academia_library":
        category = values.get("category", "all")
        if not isinstance(category, str) or category not in {"all", "syllabi", "readings", "lectures", "assessments", "notes", "other"}:
            raise McpError("Use a supported Library category.")
        location = values.get("location", "all")
        if not isinstance(location, str) or location not in {"all", "inbox", "organized"}:
            raise McpError("Use a supported Library location.")
        processing_status = values.get("processing_status", "all")
        if not isinstance(processing_status, str) or processing_status not in {"all", "not_processed", "in_progress", "processed", "failed", "untracked"}:
            raise McpError("Use a supported Library processing status.")
        limit = values.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise McpError("Library limit must be an integer from 1 to 100.")
        arguments = {
            "category": category,
            "location": location,
            "processing_status": processing_status,
            "query": str(values.get("query", "")),
            "limit": limit,
        }
        if values.get("course"):
            arguments["course"] = values["course"]
        result = _read_tool(profile, values.get("semester"), "library.list", arguments)
        items = result.data if isinstance(result.data, list) else []
        return {
            "items": items,
            "returned": len(items),
            "catalog_limit": 100,
            "truncated": bool(result.truncated),
        }
    if name == "academia_read_library_item":
        item_id = values.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise McpError("Provide an exact Library item id.")
        relative = Path(item_id)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise McpError("Library ids must be workspace-relative paths without parent-directory segments.")
        return _read_tool(profile, values.get("semester"), "library.get", {"item_id": item_id}).data
    if name == "academia_processing_status":
        return _run_cli(["process", "status"], profile)
    if name == "academia_import_targets":
        semester = values.get("semester")
        if semester is not None and (not isinstance(semester, str) or not semester.strip()):
            raise McpError("semester must be an exact non-empty folder name.")
        return _import_targets(profile, semester.strip() if isinstance(semester, str) else None)
    if name == "academia_import_file":
        source_value = values.get("source_path")
        target_id = values.get("target_id")
        if not isinstance(source_value, str) or not source_value.strip() or "\x00" in source_value:
            raise McpError("Provide the exact local source_path.")
        if not isinstance(target_id, str) or not target_id.strip():
            raise McpError("Choose an exact target_id returned by academia_import_targets.")
        source = Path(source_value).expanduser().resolve()
        if not source.is_file():
            raise McpError("The selected source_path is not a regular file.")
        target_semester = target_id.split("/", 1)[0]
        targets = _import_targets(profile, target_semester)["targets"]
        selected = next((item for item in targets if item["id"] == target_id), None)
        if selected is None:
            raise McpError("target_id must exactly match an available workspace inbox.")
        status = _run_cli(["status"], profile)
        root = status.get("workspace", {}).get("academic_root") if isinstance(status, dict) else None
        if not isinstance(root, str) or not root:
            raise McpError("Academia did not return a configured workspace path.", -32000)
        destination = Path(root).expanduser().resolve() / target_id
        args = ["import", str(source), "--destination", str(destination), "--actor", "agent:mcp"]
        source_label = _source_url_label(values.get("source_url"))
        _optional(args, "--source-label", source_label)
        result = _run_cli(args, profile)
        return {"import": result, "target": selected, "original_preserved": True, "processing_status": result.get("processing_status") if isinstance(result, dict) else None}
    raise McpError(f"Unknown Academia MCP tool: {name}")


def _response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _handle(message: Any, profile: Path | None, *, read_only: bool = False) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC request."}}
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Missing method."}}
    if "id" not in message:
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol = requested if requested in {"2024-11-05", "2025-03-26"} else _PROTOCOL_VERSION
        return _response(request_id, {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "academia-os", "title": "Academia OS", "version": __version__},
            "instructions": "Academia tools read bounded local academic context. Source bodies are available only through exact Library item ids. Before importing, ask the student to confirm the exact file and inbox; the server cannot verify that a host displayed this confirmation. Review decisions must match an exact executable choice and be confirmed by the student; execution is a separate call allowed only for an already-approved supported action. Imports preserve originals and may start local extraction. Study sets and practice are managed through Academia's Study interface. School websites remain read-only: do not submit coursework, message staff, authenticate, or access credentials.",
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": _tools_for_mode(read_only)})
    if method == "tools/call":
        name = params.get("name")
        try:
            result = _call_tool(name, params.get("arguments", {}), profile, read_only=read_only)
            return _response(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except (McpError, OSError, subprocess.TimeoutExpired, TypeError, ValueError) as exc:
            error = exc if isinstance(exc, McpError) else McpError(str(exc), -32000)
            return _response(request_id, {
                "content": [{"type": "text", "text": str(error)}],
                "isError": True,
            })
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(profile: Path | None = None, *, read_only: bool = False) -> int:
    """Read newline-delimited JSON-RPC from stdin and write protocol replies to stdout."""
    source = sys.stdin.buffer
    sink = sys.stdout.buffer
    while True:
        line = source.readline(_MAX_MESSAGE_BYTES + 1)
        if not line:
            return 0
        if len(line) > _MAX_MESSAGE_BYTES:
            message = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "MCP request exceeded the 16 MB limit."}}
        else:
            try:
                request = json.loads(line)
                message = _handle(request, profile, read_only=read_only)
            except json.JSONDecodeError:
                message = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error."}}
        if message is not None:
            sink.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            sink.flush()
