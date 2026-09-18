from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SEMESTER_PATTERN, validate_config
from .processing import ProcessingStore
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
            {"id": "create_ai_generated_artifact", "label": "Create clearly marked AI-generated secondary material", "mode": "create_only"},
            {"id": "create_non_destructive_index", "label": "Create or rebuild non-destructive local indexes", "mode": "direct"},
            {"id": "read_activity_changes", "label": "Read append-only Activity changes with a cursor", "mode": "direct"},
        ],
        "approval_required": [
            {"id": "file_move", "label": "Move a file", "mode": "explicit_approval_and_verification"},
            {"id": "file_rename", "label": "Rename a file", "mode": "explicit_approval_and_verification"},
            {"id": "destructive_structural_change", "label": "Delete or structurally reorganize academic material", "mode": "explicit_approval_and_verification"},
            {"id": "calendar_update", "label": "Change a calendar event", "mode": "explicit_approval_duplicate_check_and_verification"},
            {"id": "confirmed_academic_state_change", "label": "Change confirmed academic state after conflicting evidence", "mode": "Review_then_approved_action_then_verification"},
        ],
        "prohibited": [
            {"id": "school_submission", "label": "Submit coursework, quizzes, exams, forms, or discussions"},
            {"id": "school_message", "label": "Send school-account messages or contact academic staff/students"},
            {"id": "payment", "label": "Make payments"},
            {"id": "authentication", "label": "Authenticate as the user or handle passwords/MFA"},
            {"id": "credential_access", "label": "Read cookies, session tokens, API keys, or hidden credentials"},
            {"id": "arbitrary_original_overwrite", "label": "Overwrite ORIGINAL or EXTERNAL academic material through the artifact API"},
        ],
        "manual_import": {
            "status": "available",
            "mode": "copy_to_selected_inbox",
            "description": "academia import copies a user-selected local file into a selected workspace inbox and stages it for review.",
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

    JsonStateStore(path).update({"schema_version": 1, "records": {}}, transition)


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
    destination = destination_inbox / source.name
    counter = 1
    while destination.exists():
        destination = destination_inbox / f"{source.stem} (import {counter}){source.suffix}"
        counter += 1
    shutil.copy2(source, destination)
    metadata = {
        "source_type": "browser_upload" if source_label is not None else "manual_file",
        "original_file": source_label if source_label is not None else str(source),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "destination": str(destination),
        "provenance": "EXTERNAL",
        "confidence": "unverified",
    }
    if source_label is not None:
        metadata["source_label"] = source_label
    _record_acquisition(workspace_root, destination, metadata)
    if processing is not None:
        processing.detect(destination, signature=f"{destination.stat().st_size}:{destination.stat().st_mtime_ns}")
    return metadata
