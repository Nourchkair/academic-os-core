from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .state import JsonStateStore


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
        changed = [False]
        selected: list[ProcessingRecord] = []
        now = datetime.now(timezone.utc).isoformat()

        def transition(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
            records = [ProcessingRecord.from_dict(item) for item in raw if isinstance(item, dict) and "id" in item]
            for index, record in enumerate(records):
                if record.source_path != source:
                    continue
                if record.signature == signature:
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
