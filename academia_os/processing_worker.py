from __future__ import annotations

import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported local runtime is macOS.
    fcntl = None  # type: ignore[assignment]

from .activity import ActivityLog
from .extraction.models import ExtractionStatus
from .extraction.syllabus import extract_source_document
from .processing import ProcessingStatus, ProcessingStore, cache_signature_for_source_signature, source_signature
from .state import JsonStateStore


AUTOMATIC_EXTRACTION_EXTENSIONS = frozenset({
    ".bmp", ".docx", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".md", ".markdown",
    ".pdf", ".png", ".pptx", ".text", ".tif", ".tiff", ".txt", ".webp",
})
MAX_CONCURRENT_EXTRACTION_WORKERS = 3


def launch_processing_worker(profile_path: Path, record_id: str) -> subprocess.Popen[bytes]:
    """Start one detached local worker for an already staged processing record."""

    profile = Path(profile_path).expanduser().resolve()
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "academia_os.cli"]
    return subprocess.Popen(
        [
            *command,
            "--profile",
            str(profile),
            "process",
            "run",
            record_id,
            "--json",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


@contextmanager
def _worker_slot(state_root: Path) -> Iterator[None]:
    """Bound CPU and disk pressure when many detached workers are launched."""
    if fcntl is None:
        yield
        return
    slots = state_root / "processing-worker-slots"
    slots.mkdir(parents=True, exist_ok=True)
    while True:
        for index in range(MAX_CONCURRENT_EXTRACTION_WORKERS):
            handle = (slots / f"slot-{index}.lock").open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
            return
        time.sleep(0.2)


def process_record(workspace_root: Path, record_id: str) -> dict[str, Any]:
    """Extract one staged source with bounded concurrency across local workers."""
    root = Path(workspace_root).expanduser().resolve()
    with _worker_slot(root / ".academia"):
        return _process_record_in_slot(root, record_id)


def _process_record_in_slot(root: Path, record_id: str) -> dict[str, Any]:
    """Extract one staged source into the rebuildable local text cache."""

    state_root = root / ".academia"
    processing = ProcessingStore(state_root / "processing.json")
    record = processing.get(record_id)
    if record.status is not ProcessingStatus.PENDING:
        raise ValueError(f"processing record is {record.status.value.lower()}, not pending")

    source = Path(record.source_path).expanduser()
    relative_key: str | None = None
    started = processing.begin(record_id, lease_seconds=1800)
    try:
        source = source.resolve(strict=True)
        try:
            relative = source.relative_to(root)
        except ValueError as exc:
            raise ValueError("processing source is outside the configured academic workspace") from exc
        relative_key = relative.as_posix()
        if ".academia" in relative.parts or source.is_symlink() or not source.is_file():
            raise ValueError("processing source is not a regular workspace material file")
        if source.parent.name != "00_INBOX":
            raise ValueError("automatic extraction is limited to files directly inside a workspace inbox")
        suffix = source.suffix.casefold()
        if suffix not in AUTOMATIC_EXTRACTION_EXTENSIONS:
            raise ValueError(f"automatic extraction is not available for {suffix or 'this file type'}")

        signature = source_signature(source)
        if signature != started.signature:
            requeued = processing.requeue_changed(record_id, signature=signature)
            return {"record": asdict(requeued), "status": "requeued", "reason": "source changed before extraction"}

        document = extract_source_document(source)

        after_signature = source_signature(source)
        if after_signature != started.signature:
            requeued = processing.requeue_changed(record_id, signature=after_signature)
            return {"record": asdict(requeued), "status": "requeued", "reason": "source changed during extraction"}
        if document.status is ExtractionStatus.FAILED:
            reason = "; ".join(document.warnings) or "local source extraction failed"
            raise ValueError(reason[:500])

        document_payload = asdict(document)
        # Keep operational paths out of the rebuildable content cache.
        document_payload["path"] = relative_key
        cache = JsonStateStore(state_root / "extracted_sources.json")
        def save_extraction(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": 1, "records": {}}
            records = state.get("records")
            if not isinstance(records, dict):
                records = {}
            records[relative_key] = {
                "signature": cache_signature_for_source_signature(started.signature),
                "document": document_payload,
            }
            state["schema_version"] = 1
            state["records"] = records
            return state

        cache.update({"schema_version": 1, "records": {}}, save_extraction)

        # Check again after the cache write to avoid acknowledging an older
        # extraction if the source changed while the local index was updated.
        latest_signature = source_signature(source)
        if latest_signature != started.signature:
            requeued = processing.requeue_changed(record_id, signature=latest_signature)
            return {"record": asdict(requeued), "status": "requeued", "reason": "source changed before extraction was acknowledged"}

        verification = {
            "source_signature": started.signature,
            "content_hash": document.content_hash,
            "extraction_status": document.status.value,
            "extraction_method": document.extraction_method,
            "segment_count": len(document.segments),
            "warning_count": len(document.warnings),
            "cache_key": relative_key,
        }
        processing.verify(record_id, verification=verification)
        completed = processing.acknowledge(record_id)
        ActivityLog(state_root / "activity.jsonl").append(
            event_type="file.processed",
            title=f"Processed {source.name}",
            source=relative_key,
            details={
                "extraction_status": document.status.value,
                "extraction_method": document.extraction_method,
                "segment_count": len(document.segments),
                "warning_count": len(document.warnings),
            },
            confidence="unverified",
            actor="academia:local-worker",
        )
        return {
            "record": asdict(completed),
            "extraction_status": document.status.value,
            "segment_count": len(document.segments),
            "cache_key": relative_key,
        }
    except Exception as exc:
        current = processing.get(record_id)
        if current.status is ProcessingStatus.PROCESSING:
            processing.fail(record_id, str(exc)[:500])
            ActivityLog(state_root / "activity.jsonl").append(
                event_type="file.processing_failed",
                title=f"Could not process {source.name}",
                source=relative_key,
                details={"reason": str(exc)[:500]},
                confidence="unverified",
                actor="academia:local-worker",
            )
        raise
