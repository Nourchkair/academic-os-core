"""Durable knowledge state under <academic_root>/.academia/knowledge/."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from ..state import JsonStateStore
from .model import (
    SCHEMA_VERSION,
    Assertion,
    ChangeSet,
    Evidence,
    TaskLink,
    now,
)


def _journal_default() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "changesets": [], "events": []}


def _assertions_default() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "assertions": [], "evidence": []}


def _links_default() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "task_links": []}


def _schema_default(semester: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "updated_at": now(),
        "semester": semester,
        "field_policies": {
            "assessment.due_date": {
                "authority_scope": ["assessment.due_date"],
                "source_authority": {
                    "professor_announcement": 5,
                    "verified_external": 5,
                    "original_document": 4,
                    "external_edit": 3,
                    "student_report": 3,
                    "legacy_record": 2,
                    "ai_extraction": 1,
                    "system_projection": 0,
                },
                "verification_order": ["verified", "corroborated", "unverified", "disputed"],
                "specificity_order": ["exact", "partial", "approximate", "unknown"],
                "owner_precedence": ["assignment_history", "domain_projection", "assertion_only"],
            }
        },
        "migration": {
            "status": "not_run",
            "source_hashes": {},
            "aliases": [],
            "warnings": [],
        },
    }


class KnowledgeStore:
    """One atomic store per knowledge file.

    Reads fail closed on corruption. Writes are locked and atomically replaced.
    Missing files are represented by defaults; reads do not create directories.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.directory = self.workspace_root / ".academia" / "knowledge"
        self.schema_path = self.directory / "schema.json"
        self.assertions_path = self.directory / "assertions.json"
        self.links_path = self.directory / "links.json"
        self.journal_path = self.directory / "change_journal.json"
        self._schema = JsonStateStore(self.schema_path)
        self._assertions = JsonStateStore(self.assertions_path)
        self._links = JsonStateStore(self.links_path)
        self._journal = JsonStateStore(self.journal_path)

    @property
    def exists(self) -> bool:
        return self.directory.is_dir()

    @contextmanager
    def execution_lock(self) -> Iterator[None]:
        """Serialize ChangeSet execution across threads and processes."""
        lock_path = self.directory / ".change_execution.lock"
        with JsonStateStore(lock_path).locked():
            yield

    # Schema

    def ensure_schema(self, semester: str | None = None) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.schema_path.exists():
            self._schema.write(_schema_default(semester))
        schema = self.read_schema()
        if not isinstance(schema, dict):
            raise ValueError("knowledge schema must be an object")
        return schema

    def read_schema(self) -> dict[str, Any]:
        value = self._schema.read_strict(_schema_default())
        if not isinstance(value, dict):
            raise ValueError("knowledge schema must be an object")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported knowledge schema version: {value.get('schema_version')}")
        return value

    def write_schema(self, schema: dict[str, Any]) -> None:
        value = dict(schema)
        value["schema_version"] = SCHEMA_VERSION
        value["updated_at"] = now()
        self._schema.update_strict(_schema_default(), lambda _current: value)

    # Assertions and evidence

    def read_assertions(self) -> dict[str, Any]:
        value = self._assertions.read_strict(_assertions_default())
        if not isinstance(value, dict):
            raise ValueError("knowledge assertions state must be an object")
        if not isinstance(value.get("assertions"), list) or not isinstance(value.get("evidence"), list):
            raise ValueError("knowledge assertions state has an unsupported structure")
        return value

    def append_assertion(self, assertion: Assertion, evidence: list[Evidence] | None = None) -> Assertion:
        expected_assertion = assertion.to_dict()
        expected_evidence = [item.to_dict() for item in evidence or []]

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _assertions_default()
            assertions = list(state.get("assertions", []))
            records = list(state.get("evidence", []))
            existing = next((item for item in assertions if isinstance(item, dict) and item.get("id") == assertion.id), None)
            if existing is not None:
                if existing != expected_assertion:
                    raise ValueError(f"assertion id already exists with different content: {assertion.id}")
                return state
            by_id = {str(item.get("id")): item for item in records if isinstance(item, dict)}
            for item in expected_evidence:
                existing_evidence = by_id.get(str(item.get("id")))
                if existing_evidence is not None:
                    if existing_evidence != item:
                        raise ValueError(f"evidence id already exists with different content: {item.get('id')}")
                    continue
                records.append(item)
                by_id[str(item.get("id"))] = item
            assertions.append(expected_assertion)
            return {"schema_version": SCHEMA_VERSION, "assertions": assertions, "evidence": records}

        self._assertions.update_strict(_assertions_default(), transition)
        return assertion

    def list_assertions(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        field: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        state = self.read_assertions()
        result = []
        for item in state["assertions"]:
            if not isinstance(item, dict):
                continue
            if subject_type is not None and item.get("subject_type") != subject_type:
                continue
            if subject_id is not None and item.get("subject_id") != subject_id:
                continue
            if field is not None and item.get("field") != field:
                continue
            if status is not None and item.get("status") != status:
                continue
            result.append(dict(item))
        return result

    def get_assertion(self, assertion_id: str) -> dict[str, Any]:
        for item in self.read_assertions()["assertions"]:
            if isinstance(item, dict) and item.get("id") == assertion_id:
                return dict(item)
        raise KeyError(f"assertion not found: {assertion_id}")

    def update_assertions(self, transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> None:
        def guarded(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _assertions_default()
            assertions = [dict(item) for item in state.get("assertions", []) if isinstance(item, dict)]
            evidence = list(state.get("evidence", []))
            return {"schema_version": SCHEMA_VERSION, "assertions": transform(assertions), "evidence": evidence}

        self._assertions.update_strict(_assertions_default(), guarded)

    def activate_assertion(self, assertion_id: str, *, applied_change_id: str | None = None, supersede: bool = True) -> dict[str, Any]:
        """Make one assertion active and supersede earlier active values.

        Superseding is a status change, never a deletion. The old assertion and
        its evidence remain available for audit and reversal history.
        """
        selected: dict[str, Any] = {}
        timestamp = now()

        def transition(assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal selected
            target = next((item for item in assertions if item.get("id") == assertion_id), None)
            if target is None:
                raise KeyError(f"assertion not found: {assertion_id}")
            target["status"] = "active"
            target["updated_at"] = timestamp
            if applied_change_id is not None:
                target["applied_change_id"] = applied_change_id
            if supersede:
                for item in assertions:
                    if item is target or item.get("subject_type") != target.get("subject_type") or item.get("subject_id") != target.get("subject_id") or item.get("field") != target.get("field"):
                        continue
                    if item.get("status") != "active" or item.get("value") == target.get("value"):
                        continue
                    # Supersede owner projections and prior applied values, not
                    # independent source claims. A current professor announcement
                    # must remain visible as a disagreement.
                    if item.get("source_kind") not in {"legacy_record", "external_edit", "system_projection"} and not item.get("applied_change_id"):
                        continue
                    item["status"] = "superseded"
                    item["updated_at"] = timestamp
                    superseded_by = list(item.get("superseded_by", []))
                    if assertion_id not in superseded_by:
                        superseded_by.append(assertion_id)
                    item["superseded_by"] = superseded_by
            selected = dict(target)
            return assertions

        self.update_assertions(transition)
        return selected

    def reject_assertion(self, assertion_id: str, *, reason: str | None = None, change_id: str | None = None) -> dict[str, Any]:
        selected: dict[str, Any] = {}
        timestamp = now()

        def transition(assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal selected
            target = next((item for item in assertions if item.get("id") == assertion_id), None)
            if target is None:
                raise KeyError(f"assertion not found: {assertion_id}")
            target["status"] = "rejected"
            target["updated_at"] = timestamp
            metadata = dict(target.get("metadata", {}))
            if reason:
                metadata["rejection_reason"] = reason
            if change_id:
                metadata["rejected_change_id"] = change_id
            target["metadata"] = metadata
            selected = dict(target)
            return assertions

        self.update_assertions(transition)
        return selected

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        for item in self.read_assertions()["evidence"]:
            if isinstance(item, dict) and item.get("id") == evidence_id:
                return dict(item)
        raise KeyError(f"evidence not found: {evidence_id}")

    def evidence_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("id")): dict(item)
            for item in self.read_assertions()["evidence"]
            if isinstance(item, dict) and item.get("id")
        }

    # Links

    def read_links(self) -> dict[str, Any]:
        value = self._links.read_strict(_links_default())
        if not isinstance(value, dict):
            raise ValueError("knowledge links state must be an object")
        if not isinstance(value.get("task_links"), list):
            raise ValueError("knowledge links state has an unsupported structure")
        return value

    def list_links(
        self,
        *,
        assessment_id: str | None = None,
        task_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for item in self.read_links()["task_links"]:
            if not isinstance(item, dict):
                continue
            if assessment_id is not None and item.get("assessment_id") != assessment_id:
                continue
            if task_id is not None and item.get("task_id") != task_id:
                continue
            if status is not None and item.get("status") != status:
                continue
            result.append(dict(item))
        return result

    def get_link(self, link_id: str) -> dict[str, Any]:
        for item in self.read_links()["task_links"]:
            if isinstance(item, dict) and item.get("id") == link_id:
                return dict(item)
        raise KeyError(f"task link not found: {link_id}")

    def upsert_link(self, link: TaskLink) -> TaskLink:
        expected = link.to_dict()

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _links_default()
            values = [item for item in state.get("task_links", []) if isinstance(item, dict) and item.get("id") != link.id]
            values.append(expected)
            values.sort(key=lambda item: str(item.get("id", "")))
            return {"schema_version": SCHEMA_VERSION, "task_links": values}

        self._links.update_strict(_links_default(), transition)
        return link

    # Change journal

    def read_journal(self) -> dict[str, Any]:
        value = self._journal.read_strict(_journal_default())
        if not isinstance(value, dict):
            raise ValueError("change journal must be an object")
        if not isinstance(value.get("changesets"), list) or not isinstance(value.get("events"), list):
            raise ValueError("change journal has an unsupported structure")
        return value

    def write_journal(self, journal: dict[str, Any]) -> None:
        value = dict(journal)
        value["schema_version"] = SCHEMA_VERSION
        self._journal.update_strict(_journal_default(), lambda _current: value)

    def mutate_journal(self, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        def guarded(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _journal_default()
            state.setdefault("changesets", [])
            state.setdefault("events", [])
            value = transform(state)
            value["schema_version"] = SCHEMA_VERSION
            return value

        return self._journal.update_strict(_journal_default(), guarded)

    def list_changesets(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.read_journal()["changesets"] if isinstance(item, dict)]

    def get_changeset(self, changeset_id: str) -> dict[str, Any]:
        for item in self.read_journal()["changesets"]:
            if isinstance(item, dict) and item.get("id") == changeset_id:
                return dict(item)
        raise KeyError(f"changeset not found: {changeset_id}")

    def save_changeset(self, changeset: ChangeSet) -> ChangeSet:
        expected = changeset.to_dict()

        def transform(state: dict[str, Any]) -> dict[str, Any]:
            changesets = [item for item in state.get("changesets", []) if isinstance(item, dict) and item.get("id") != changeset.id]
            changesets.append(expected)
            changesets.sort(key=lambda item: str(item.get("id", "")))
            return {**state, "changesets": changesets}

        self.mutate_journal(transform)
        return changeset

    def append_event(
        self,
        *,
        changeset_id: str,
        event_type: str,
        actor: str,
        channel: str,
        operation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {}

        def transform(state: dict[str, Any]) -> dict[str, Any]:
            nonlocal event
            events = list(state.get("events", []))
            next_id = max((int(item.get("id", 0)) for item in events if isinstance(item, dict)), default=0) + 1
            event = {
                "id": next_id,
                "at": now(),
                "changeset_id": changeset_id,
                "operation_id": operation_id,
                "type": event_type,
                "actor": actor,
                "channel": channel,
                "details": details or {},
            }
            events.append(event)
            return {**state, "events": events}

        self.mutate_journal(transform)
        return event
