from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SEMESTER_PATTERN, validate_config
from .processing import ProcessingStore, source_signature
from .source_identity import SourceIdentityError, fingerprint
from .state import JsonStateStore


def browser_access_policy(config: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_config(config)
    browser = normalized["browser"]
    return {
        "enabled": bool(browser.get("access_enabled", False)),
        "allowed_sites": list(browser.get("allowed_sites", [])),
        "dedicated_profile_recommended": bool(normalized["privacy"].get("dedicated_profile_recommended", True)),
    }


@dataclass(frozen=True)
class AcquisitionSource:
    source_type: str
    label: str
    browser: str | None = None
    source_url: str | None = None
    acquired_at: str = ""
    original_file: str | None = None


def acquisition_defaults() -> dict[str, Any]:
    return {
        "manual_import_enabled": True,
        "watched_folders": [],
        "browser_companion_enabled": False,
        "browser": {
            "access_enabled": False,
            "allowed_sites": [],
        },
    }


def capability_report() -> dict[str, Any]:
    """Return implementation details plus hard agent permission categories.

    The categorized entries are the stable machine-facing contract.  The named
    acquisition/browser entries remain for compatibility with the earlier CLI.
    """
    return {
        "schema_version": 1,
        "allowed_directly": [
            {"id": "read_structured_context", "label": "Read structured academic context", "mode": "direct"},
            {"id": "read_authorized_workspace_files", "label": "Read authorized academic files through bounded workspace interfaces", "mode": "direct"},
            {"id": "inspect_domain_state", "label": "Inspect evidence-backed domain state", "mode": "direct"},
            {"id": "inspect_review", "label": "Inspect unresolved Review decisions", "mode": "direct"},
            {"id": "create_non_destructive_index", "label": "Create or rebuild non-destructive local indexes", "mode": "direct"},
            {"id": "study", "label": "Create cited study sets, run practice, record student answers and review progress through academia study", "mode": "shared_cli_api"},
            {"id": "read_activity_changes", "label": "Read append-only Activity changes with a cursor", "mode": "direct"},
            {"id": "record_user_confirmed_coursework", "label": "Record and update user-confirmed assignment and project history", "mode": "user_confirmed_workspace_record"},
            {"id": "manage_user_tasks", "label": "Create, update, complete, or reopen personal tasks in SEMESTER_TASKS.md", "mode": "user_confirmed_workspace_record"},
        ],
        "study": {"status": "available", "interface": "academia study", "dashboard_required": False,
                  "generation": ["external_agent", "codex_chatgpt_plan", "local_model"],
                  "credentials_owned_by": "external provider", "practice_changes_course_grades": False},
        "approval_required": [
            {"id": "file_move", "label": "Move a file", "mode": "explicit_approval_and_verification"},
            {"id": "file_rename", "label": "Rename a file", "mode": "explicit_approval_and_verification"},
            {"id": "destructive_structural_change", "label": "Delete or structurally reorganize academic material", "mode": "explicit_approval_and_verification"},
            {"id": "calendar_update", "label": "Change a calendar event", "mode": "explicit_approval_duplicate_check_and_verification"},
            {"id": "confirmed_academic_state_change", "label": "Change confirmed academic state after conflicting evidence", "mode": "Review_then_approved_action_then_verification"},
            {"id": "agent_task_change", "label": "Create or update a personal task proposed by an agent", "mode": "Review_then_approved_action_then_verification"},
        ],
        "prohibited": [
            {"id": "school_submission", "label": "Submit coursework, quizzes, exams, forms, or discussions"},
            {"id": "school_message", "label": "Send school-account messages or contact academic staff/students"},
            {"id": "payment", "label": "Payment capability is not implemented; agents must never infer payment authorization"},
            {"id": "authentication", "label": "Authenticate as the user or handle passwords/MFA"},
            {"id": "credential_access", "label": "Read cookies, session tokens, API keys, or hidden credentials"},
            {"id": "arbitrary_original_overwrite", "label": "Overwrite ORIGINAL or EXTERNAL academic material through Academia's supported write interfaces"},
        ],
        "manual_import": {
            "status": "available",
            "mode": "copy_and_background_extract",
            "description": "academia import and the local MCP import tool copy a student-confirmed file into a recognized direct workspace inbox and automatically extract supported local text formats in a background worker; originals are preserved and PDFs without extractable text are reported as needing OCR.",
        },
        "mcp": {
            "status": "available",
            "transport": "local_stdio",
            "read_tools": ["status", "capabilities", "courses", "today", "tasks", "agent_context", "attention", "review_item", "activity_changes", "library", "read_library_item", "processing_status", "import_targets"],
            "write_tools": ["review_decide", "review_execute", "import_file"],
            "proposal_tools": ["propose_import", "propose_task"],
            "external_connectors": "not_provided_by_core_mcp",
        },
        "watched_folders": {
            "status": "available",
            "mode": "one_shot_scan",
            "description": "academia watch performs a one-shot scan of configured folders; persistent background watching is not claimed yet.",
        },
        "browser_companion": {"status": "planned", "description": "A future explicit Send to Academia OS companion interface."},
        "chromium": {"status": "available", "mode": "visible_handoff_only", "description": "Optional Chromium-family visible handoff requires an explicit allowed-site and never reads credential/session data."},
        "firefox": {"status": "planned", "description": "No Firefox automation adapter is claimed yet."},
        "safari": {"status": "planned", "description": "No Safari automation adapter is claimed yet."},
    }


def configured_watched_folders(config: dict[str, Any]) -> list[Path]:
    normalized = validate_config(config)
    return [Path(value).expanduser().resolve() for value in normalized["acquisition"].get("watched_folders", []) if isinstance(value, str) and value.strip()]


def scan_watched_folder(path: Path, *, since: datetime | None = None) -> list[Path]:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        return []
    candidates: list[Path] = []
    for item in sorted(path.rglob("*")):
        if not item.is_file() or item.name.startswith(".") or item.suffix.lower() in {".part", ".crdownload", ".tmp"}:
            continue
        if since is not None:
            modified = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
            if modified <= since:
                continue
        candidates.append(item)
    return candidates


def validate_import_destination(workspace_root: Path, destination_inbox: Path) -> Path:
    workspace_root = Path(workspace_root).expanduser().resolve()
    destination_inbox = Path(destination_inbox).expanduser().resolve()
    try:
        relative = destination_inbox.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("import destination must be inside the configured academic workspace") from exc
    if not relative.parts or ".academia" in relative.parts:
        raise ValueError("import destination must be a workspace inbox, not the workspace root or operational state")
    if relative.parts[-1] != "00_INBOX":
        raise ValueError("import destination must end in a direct 00_INBOX workspace inbox")
    if len(relative.parts) not in {2, 3}:
        raise ValueError("import destination must be a direct semester inbox or direct course inbox")
    semester_name = relative.parts[0]
    semester_root = workspace_root / semester_name
    if SEMESTER_PATTERN.fullmatch(semester_name) is None or not semester_root.is_dir():
        raise ValueError("import destination must use a recognized semester directory")
    if len(relative.parts) == 3:
        course_root = semester_root / relative.parts[1]
        if not course_root.is_dir() or not (course_root / "01_COURSE").is_dir():
            raise ValueError("import destination must use a recognized course belonging to that semester")
    return destination_inbox


def validate_import_source(source: Path) -> Path:
    source = Path(source).expanduser().resolve()
    if ".academia" in source.parts:
        raise ValueError("academic operational state cannot be imported as source material")
    return source


def _record_acquisition(workspace_root: Path, destination: Path, metadata: dict[str, Any]) -> None:
    root = Path(workspace_root).expanduser().resolve()
    relative = destination.resolve().relative_to(root).as_posix()
    path = root / ".academia" / "acquisition.json"

    def transition(raw: dict[str, Any]) -> dict[str, Any]:
        state = raw if isinstance(raw, dict) else {"schema_version": 1, "records": {}}
        records_value = state.get("records")
        records: dict[str, Any] = records_value if isinstance(records_value, dict) else {}
        records[relative] = dict(metadata)
        state["schema_version"] = 1
        state["records"] = records
        return state

    JsonStateStore(path).update_strict({"schema_version": 1, "records": {}}, transition)


def _source_digest(source: Path) -> str:
    try:
        return fingerprint(source, max_bytes=1024 * 1024 * 1024)
    except SourceIdentityError as exc:
        raise ValueError(str(exc)) from exc


def _find_duplicate(destination_inbox: Path, digest: str) -> Path | None:
    for candidate in sorted(destination_inbox.iterdir()):
        if candidate.is_symlink() or not candidate.is_file() or candidate.name.startswith("."):
            continue
        try:
            if _source_digest(candidate) == digest:
                return candidate
        except (OSError, ValueError):
            continue
    return None


def _copy_atomic(source: Path, destination: Path, digest: str) -> None:
    stat = source.stat()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    copied_digest = hashlib.sha256()
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            descriptor = -1
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
                copied_digest.update(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        if copied_digest.hexdigest() != digest:
            raise ValueError("source file changed during import; no destination file was committed")
        os.chmod(temporary, stat.st_mode & 0o777)
        os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise ValueError("import destination appeared during copy; choose a new import") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def import_file(
    source: Path,
    destination_inbox: Path,
    processing: ProcessingStore | None = None,
    *,
    workspace_root: Path | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    source = validate_import_source(source)
    if source_label is not None:
        if not isinstance(source_label, str) or not source_label.strip() or "\x00" in source_label:
            raise ValueError("source label must be a non-empty string without NUL bytes")
    if workspace_root is None:
        raise ValueError("workspace root is required for structural import validation")
    destination_inbox = validate_import_destination(workspace_root, destination_inbox)
    if not source.is_file():
        raise FileNotFoundError(source)
    destination_inbox.mkdir(parents=True, exist_ok=True)
    # Fail before copying anything if provenance state is already damaged.
    acquisition_store = JsonStateStore(Path(workspace_root).expanduser().resolve() / ".academia" / "acquisition.json")
    acquisition_store.read_strict({"schema_version": 1, "records": {}})
    digest = _source_digest(source)
    duplicate = _find_duplicate(destination_inbox, digest)
    if duplicate is not None:
        return {
            "source_type": "browser_upload" if source_label is not None and source_label.startswith("browser-upload:") else "manual_file",
            "original_file": source_label if source_label is not None else str(source),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "destination": str(duplicate),
            "provenance": "EXTERNAL",
            "confidence": "unverified",
            "source_sha256": digest,
            "duplicate": True,
            "duplicate_of": duplicate.relative_to(Path(workspace_root).expanduser().resolve()).as_posix(),
        }
    destination = destination_inbox / source.name
    counter = 1
    while destination.exists():
        destination = destination_inbox / f"{source.stem} (import {counter}){source.suffix}"
        counter += 1
    _copy_atomic(source, destination, digest)
    metadata = {
        "source_type": "browser_upload" if source_label is not None and source_label.startswith("browser-upload:") else "manual_file",
        "original_file": source_label if source_label is not None else str(source),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "destination": str(destination),
        "provenance": "EXTERNAL",
        "confidence": "unverified",
        "source_sha256": digest,
    }
    if source_label is not None:
        metadata["source_label"] = source_label
    try:
        _record_acquisition(workspace_root, destination, metadata)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if processing is not None:
        record = processing.detect(destination, signature=source_signature(destination))
        metadata["processing_record_id"] = record.id
        metadata["processing_status"] = record.status.value
    return metadata
