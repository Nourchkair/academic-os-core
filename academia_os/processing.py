from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .state import JsonStateStore


def source_signature(source_path: Path) -> str:
    """Return the fingerprint shared with the inbox gate and extraction workers."""
    stat = Path(source_path).stat()
    return json.dumps(
        {
            "inode": int(getattr(stat, "st_ino", 0)),
            "mtime_ns": int(stat.st_mtime_ns),
            "size": int(stat.st_size),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def cache_signature(source_path: Path) -> str:
    """Return the stable size/mtime key used by the rebuildable text cache."""
    stat = Path(source_path).stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _canonical_signature(signature: str) -> str:
    """Normalize JSON and early size/mtime fingerprints without losing inode data."""
    try:
        value = json.loads(signature)
    except (TypeError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict) and "size" in value and "mtime_ns" in value:
        try:
            normalized = {"mtime_ns": int(value["mtime_ns"]), "size": int(value["size"])}
            if "inode" in value:
                normalized["inode"] = int(value["inode"])
            return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return signature
    try:
        size, mtime_ns = signature.split(":", 1)
        return f"{int(size)}:{int(mtime_ns)}"
    except (AttributeError, TypeError, ValueError):
        return signature


def _signature_fields(signature: str) -> dict[str, int] | None:
    normalized = _canonical_signature(signature)
    try:
        value = json.loads(normalized)
    except (TypeError, json.JSONDecodeError):
        value = None
    if isinstance(value, dict):
        try:
            fields = {"size": int(value["size"]), "mtime_ns": int(value["mtime_ns"])}
            if "inode" in value:
                fields["inode"] = int(value["inode"])
            return fields
        except (KeyError, TypeError, ValueError):
            return None
    try:
        size, mtime_ns = normalized.split(":", 1)
        return {"size": int(size), "mtime_ns": int(mtime_ns)}
    except (AttributeError, TypeError, ValueError):
        return None


def cache_signature_for_source_signature(signature: str) -> str:
    """Project a processing fingerprint onto the text-cache fingerprint."""
    fields = _signature_fields(signature)
    if fields is None:
        return signature
    return f"{fields['size']}:{fields['mtime_ns']}"


def _signatures_match(left: str, right: str) -> bool:
    first = _signature_fields(left)
    second = _signature_fields(right)
    if first is None or second is None:
        return left == right
    if first["size"] != second["size"] or first["mtime_ns"] != second["mtime_ns"]:
        return False
    # Legacy size/mtime records did not retain inode information. Preserve
    # their status during migration; when both fingerprints have an inode,
    # replacements at the same path are detected as source changes.
    return "inode" not in first or "inode" not in second or first["inode"] == second["inode"]


class ProcessingStatus(StrEnum):
    DETECTED = "DETECTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    VERIFIED = "VERIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


@dataclass
class ProcessingRecord:
    id: str
    source_path: str
    signature: str
    status: ProcessingStatus
    detected_at: str
    updated_at: str
    retry_count: int = 0
    lease_until: str | None = None
    failure_reason: str | None = None
    verification: dict[str, Any] | None = None
    acknowledged_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProcessingRecord":
        return cls(
            id=str(value["id"]), source_path=str(value["source_path"]), signature=str(value["signature"]),
            status=ProcessingStatus(value.get("status", ProcessingStatus.PENDING)), detected_at=str(value["detected_at"]),
            updated_at=str(value["updated_at"]), retry_count=int(value.get("retry_count", 0)), lease_until=value.get("lease_until"),
            failure_reason=value.get("failure_reason"), verification=value.get("verification"), acknowledged_at=value.get("acknowledged_at"),
        )


class ProcessingStore:
    def __init__(self, path: Path) -> None:
        self.store = JsonStateStore(path)
        self.last_detection_changed = False

    def _records(self) -> list[ProcessingRecord]:
        value = self.store.read([])
        return [ProcessingRecord.from_dict(item) for item in value if isinstance(item, dict) and "id" in item] if isinstance(value, list) else []

    def _save(self, records: list[ProcessingRecord]) -> None:
        self.store.write([asdict(record) for record in records])

    def detect(self, source_path: Path, *, signature: str) -> ProcessingRecord:
        source = str(Path(source_path).expanduser().resolve())
        signature = _canonical_signature(signature)
        changed = [False]
        selected: list[ProcessingRecord] = []
        now = datetime.now(timezone.utc).isoformat()

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, record in enumerate(records):
                if record.source_path != source:
                    continue
                if _signatures_match(record.signature, signature):
                    if record.signature != signature:
                        # Migrate equivalent signatures without reopening work
                        # that was already verified and acknowledged.
                        record.signature = signature
                        records[index] = record
                    selected.append(record)
                    return [asdict(item) for item in records]
                # An inbox scan may run while the worker is extracting this
                # file. Keep the worker's lease and queued signature intact;
                # the worker will compare signatures after extraction and
                # safely requeue the newer version if the file changed.
                if record.status is ProcessingStatus.PROCESSING:
                    selected.append(record)
                    return [asdict(item) for item in records]
                record.signature = signature
                record.status = ProcessingStatus.PENDING
                record.updated_at = now
                record.failure_reason = None
                record.lease_until = None
                record.verification = None
                record.acknowledged_at = None
                records[index] = record
                changed[0] = True
                selected.append(record)
                return [asdict(item) for item in records]
            record = ProcessingRecord(str(abs(hash((source, signature)))), source, signature, ProcessingStatus.PENDING, now, now)
            records.append(record)
            changed[0] = True
            selected.append(record)
            return [asdict(item) for item in records]

        self.store.update([], transition)
        self.last_detection_changed = changed[0]
        return selected[0]

    def get(self, record_id: str) -> ProcessingRecord:
        for record in self._records():
            if record.id == record_id:
                return record
        raise KeyError(f"processing record not found: {record_id}")

    def _replace(self, updated: ProcessingRecord) -> ProcessingRecord:
        selected: list[ProcessingRecord] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, record in enumerate(records):
                if record.id == updated.id:
                    records[index] = updated
                    selected.append(updated)
                    return [asdict(item) for item in records]
            raise KeyError(f"processing record not found: {updated.id}")

        self.store.update([], transition)
        return selected[0]

    def _transition_record(self, record_id: str, expected: ProcessingStatus, mutator: Any) -> ProcessingRecord:
        selected: list[ProcessingRecord] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, record in enumerate(records):
                if record.id != record_id:
                    continue
                if record.status is not expected:
                    raise ValueError(f"record {record_id} is not {expected.value.lower()}")
                updated = mutator(record)
                records[index] = updated
                selected.append(updated)
                return [asdict(item) for item in records]
            raise KeyError(f"processing record not found: {record_id}")

        self.store.update([], transition)
        return selected[0]

    def begin(self, record_id: str, *, lease_seconds: int = 300) -> ProcessingRecord:
        now = datetime.now(timezone.utc)

        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            record.status = ProcessingStatus.PROCESSING
            record.updated_at = now.isoformat()
            record.lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.PENDING, mutate)

    def requeue_changed(self, record_id: str, *, signature: str) -> ProcessingRecord:
        """Return a changed in-flight source to the queue without recording failure."""
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            record.signature = signature
            record.status = ProcessingStatus.PENDING
            record.failure_reason = None
            record.lease_until = None
            record.verification = None
            record.acknowledged_at = None
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.PROCESSING, mutate)

    def fail(self, record_id: str, reason: str) -> ProcessingRecord:
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            record.status = ProcessingStatus.FAILED
            record.failure_reason = reason
            record.retry_count += 1
            record.lease_until = None
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.PROCESSING, mutate)

    def retry(self, record_id: str) -> ProcessingRecord:
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            record.status = ProcessingStatus.PENDING
            record.failure_reason = None
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.FAILED, mutate)

    def requeue_unsupported_ocr(self, record_id: str) -> ProcessingRecord:
        """Reprocess an acknowledged source whose prior pass lacked OCR support."""
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            verification = record.verification or {}
            if verification.get("extraction_status") != "unsupported_without_ocr":
                raise ValueError("only sources previously acknowledged without OCR can be reprocessed")
            record.status = ProcessingStatus.PENDING
            record.failure_reason = None
            record.lease_until = None
            record.verification = None
            record.acknowledged_at = None
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.ACKNOWLEDGED, mutate)

    def forget_missing_failed(self, record_id: str, *, workspace_root: Path) -> ProcessingRecord:
        """Remove a failed processing record only when its inbox source is gone."""
        root = Path(workspace_root).expanduser().resolve()
        selected: list[ProcessingRecord] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for record in records:
                if record.id != record_id:
                    continue
                if record.status is not ProcessingStatus.FAILED:
                    raise ValueError("only failed processing records can be forgotten")
                source = Path(record.source_path).expanduser().resolve()
                try:
                    relative = source.relative_to(root)
                except ValueError as exc:
                    raise ValueError("processing source is outside the configured academic workspace") from exc
                if ".academia" in relative.parts or relative.parent.name != "00_INBOX" or len(relative.parts) not in {3, 4}:
                    raise ValueError("only semester or course inbox records can be forgotten")
                if source.exists():
                    raise ValueError("source file still exists; processing record was not forgotten")
                selected.append(record)
                return [asdict(item) for item in records if item.id != record_id]
            raise KeyError(f"processing record not found: {record_id}")

        self.store.update([], transition)
        return selected[0]

    def verify(self, record_id: str, *, verification: dict[str, Any]) -> ProcessingRecord:
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            record.status = ProcessingStatus.VERIFIED
            record.verification = verification
            record.lease_until = None
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

        return self._transition_record(record_id, ProcessingStatus.PROCESSING, mutate)

    def acknowledge(self, record_id: str) -> ProcessingRecord:
        def mutate(record: ProcessingRecord) -> ProcessingRecord:
            now = datetime.now(timezone.utc).isoformat()
            record.status = ProcessingStatus.ACKNOWLEDGED
            record.acknowledged_at = now
            record.updated_at = now
            return record

        return self._transition_record(record_id, ProcessingStatus.VERIFIED, mutate)

    def restore_acknowledged(self, record_id: str, *, signature: str, verification: dict[str, Any]) -> ProcessingRecord:
        """Restore a completed state when a matching extraction cache survived."""
        selected: list[ProcessingRecord] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, record in enumerate(records):
                if record.id != record_id:
                    continue
                # A concurrent worker or a newer source version takes priority
                # over cache-based state recovery.
                if record.status in {ProcessingStatus.ACKNOWLEDGED, ProcessingStatus.PROCESSING} or not _signatures_match(record.signature, signature):
                    selected.append(record)
                    return [asdict(item) for item in records]
                now = datetime.now(timezone.utc).isoformat()
                record.status = ProcessingStatus.ACKNOWLEDGED
                record.failure_reason = None
                record.lease_until = None
                record.verification = {**verification, "recovered_from_cache": True}
                record.acknowledged_at = now
                record.updated_at = now
                records[index] = record
                selected.append(record)
                return [asdict(item) for item in records]
            raise KeyError(f"processing record not found: {record_id}")

        self.store.update([], transition)
        return selected[0]

    def recover_stale(self, *, now: datetime | None = None) -> list[ProcessingRecord]:
        current = now or datetime.now(timezone.utc)
        recovered: list[ProcessingRecord] = []

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for record in records:
                if record.status is not ProcessingStatus.PROCESSING or not record.lease_until:
                    continue
                try:
                    expired = datetime.fromisoformat(record.lease_until) <= current
                except ValueError:
                    expired = True
                if expired:
                    record.status = ProcessingStatus.PENDING
                    record.retry_count += 1
                    record.lease_until = None
                    record.updated_at = current.isoformat()
                    recovered.append(record)
            return [asdict(item) for item in records]

        if self.store.path.exists():
            self.store.update([], transition)
        return recovered

    def list(self) -> list[ProcessingRecord]:
        """Return persisted records without changing their lifecycle state."""
        return self._records()

    def pending(self) -> list[ProcessingRecord]:
        return [record for record in self._records() if record.status in {ProcessingStatus.PENDING, ProcessingStatus.FAILED, ProcessingStatus.PROCESSING, ProcessingStatus.VERIFIED}]
