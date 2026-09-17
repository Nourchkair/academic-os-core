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
        records = self._records()
        now = datetime.now(timezone.utc).isoformat()
        for index, record in enumerate(records):
            if record.source_path != source:
                continue
            if record.signature == signature:
                self.last_detection_changed = False
                return record
            record.signature = signature
            record.status = ProcessingStatus.PENDING
            record.updated_at = now
            record.failure_reason = None
            record.lease_until = None
            record.verification = None
            record.acknowledged_at = None
            records[index] = record
            self._save(records)
            self.last_detection_changed = True
            return record
        record = ProcessingRecord(str(abs(hash((source, signature)))), source, signature, ProcessingStatus.DETECTED, now, now)
        record.status = ProcessingStatus.PENDING
        records.append(record)
        self._save(records)
        self.last_detection_changed = True
        return record

    def get(self, record_id: str) -> ProcessingRecord:
        for record in self._records():
            if record.id == record_id:
                return record
        raise KeyError(f"processing record not found: {record_id}")

    def _replace(self, updated: ProcessingRecord) -> ProcessingRecord:
        records = self._records()
        for index, record in enumerate(records):
            if record.id == updated.id:
                records[index] = updated
                self._save(records)
                return updated
        raise KeyError(f"processing record not found: {updated.id}")

    def begin(self, record_id: str, *, lease_seconds: int = 300) -> ProcessingRecord:
        record = self.get(record_id)
        if record.status is not ProcessingStatus.PENDING:
            raise ValueError(f"record {record_id} is not pending")
        record.status = ProcessingStatus.PROCESSING
        record.updated_at = datetime.now(timezone.utc).isoformat()
        record.lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        return self._replace(record)

    def fail(self, record_id: str, reason: str) -> ProcessingRecord:
        record = self.get(record_id)
        if record.status is not ProcessingStatus.PROCESSING:
            raise ValueError(f"record {record_id} is not processing")
        record.status = ProcessingStatus.FAILED
        record.failure_reason = reason
        record.retry_count += 1
        record.lease_until = None
        record.updated_at = datetime.now(timezone.utc).isoformat()
        return self._replace(record)

    def retry(self, record_id: str) -> ProcessingRecord:
        record = self.get(record_id)
        if record.status is not ProcessingStatus.FAILED:
            raise ValueError(f"record {record_id} is not failed")
        record.status = ProcessingStatus.PENDING
        record.failure_reason = None
        record.updated_at = datetime.now(timezone.utc).isoformat()
        return self._replace(record)

    def verify(self, record_id: str, *, verification: dict[str, Any]) -> ProcessingRecord:
        record = self.get(record_id)
        if record.status is not ProcessingStatus.PROCESSING:
            raise ValueError(f"record {record_id} is not processing")
        record.status = ProcessingStatus.VERIFIED
        record.verification = verification
        record.lease_until = None
        record.updated_at = datetime.now(timezone.utc).isoformat()
        return self._replace(record)

    def acknowledge(self, record_id: str) -> ProcessingRecord:
        record = self.get(record_id)
        if record.status is not ProcessingStatus.VERIFIED:
            raise ValueError(f"record {record_id} is not verified")
        now = datetime.now(timezone.utc).isoformat()
        record.status = ProcessingStatus.ACKNOWLEDGED
        record.acknowledged_at = now
        record.updated_at = now
        return self._replace(record)

    def recover_stale(self, *, now: datetime | None = None) -> list[ProcessingRecord]:
        current = now or datetime.now(timezone.utc)
        records = self._records()
        recovered: list[ProcessingRecord] = []
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
        if recovered:
            self._save(records)
        return recovered

    def pending(self) -> list[ProcessingRecord]:
        return [record for record in self._records() if record.status in {ProcessingStatus.PENDING, ProcessingStatus.FAILED, ProcessingStatus.PROCESSING, ProcessingStatus.VERIFIED}]
