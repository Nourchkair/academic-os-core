"""Knowledge reads, migration, links, and ChangeSet lifecycle."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..activity import ActivityLog
from ..assignment_history import update_assignment_history
from ..config import SEMESTER_PATTERN
from ..course_identity import course_records, resolve_course_identifier
from ..domain import DomainProjection
from ..tasks import TaskStore
from .model import (
    AGENT_ACTOR_PREFIX,
    AGENT_CHANNELS,
    USER_ACTORS,
    USER_CHANNELS,
    Assertion,
    ChangeSet,
    Evidence,
    Operation,
    TaskLink,
    approval_hash,
    date_text,
    new_id,
    now,
    sha256_json,
    sha256_text,
)
from .resolver import (
    assessment_revision,
    build_assessments,
    build_course_assessments,
    public_assessment,
    resolve_assessment,
    resolve_field,
)
from .store import KnowledgeStore


def _file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _task_revision(task: dict[str, Any]) -> str:
    return "sha256:" + sha256_json({"id": task.get("id"), "field": "due_date", "value": task.get("due_date")})


class KnowledgeService:
    def __init__(self, workspace_root: Path, semester: str) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if SEMESTER_PATTERN.fullmatch(semester) is None:
            raise ValueError("semester must use a term and four-digit year, such as Fall 2026")
        self.root = root
        self.semester = semester
        self.store = KnowledgeStore(root)

    # Shared helpers

    def _course(self, course_id: str) -> dict[str, Any]:
        semester_root = self.root / self.semester
        if not semester_root.is_dir():
            raise KeyError(f"semester not found: {self.semester}")
        return resolve_course_identifier(course_records(semester_root), course_id)

    def _course_root(self, course_id: str) -> Path:
        return Path(str(self._course(course_id)["path"]))

    def _activity(self) -> ActivityLog:
        return ActivityLog(self.root / ".academia" / "activity.jsonl")

    def _require_user(self, actor: str, channel: str) -> None:
        if actor.startswith(AGENT_ACTOR_PREFIX) or channel in AGENT_CHANNELS:
            raise PermissionError("an agent may propose changes but may not approve, link, or reverse them")
        if actor not in USER_ACTORS or channel not in USER_CHANNELS:
            raise PermissionError("a user-authorized dashboard or CLI channel is required")

    def _safe_evidence_path(self, raw: str | None) -> Path | None:
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("evidence file must remain inside the academic workspace") from exc
        if ".academia" in relative.parts:
            raise ValueError("evidence file must be academic material, not operational state")
        if not resolved.is_file():
            raise ValueError(f"evidence file not found: {raw}")
        return resolved

    def _assessment(self, course_id: str, assessment_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        assessments, _deadlines, warnings, _context = build_assessments(self.store, self.root, self.semester, course_id)
        selected = resolve_assessment(assessments, assessment_id)
        if str(selected.get("course_id")) != str(self._course(course_id)["id"]):
            raise ValueError("assessment does not belong to the selected course")
        return selected, assessments, warnings

    def _assertions_for(self, assessment_id: str) -> list[dict[str, Any]]:
        return self.store.list_assertions(subject_type="assessment", subject_id=assessment_id, field="due_date", status="active")

    # Reads

    def _stale_evidence_ids(self, evidence_ids: set[str] | None = None) -> set[str]:
        stale: set[str] = set()
        cache: dict[Path, str | None] = {}
        evidence_map = self.store.evidence_map()
        for evidence_id, evidence in evidence_map.items():
            if evidence_ids is not None and evidence_id not in evidence_ids:
                continue
            source_path = evidence.get("source_path")
            digest = evidence.get("sha256")
            if not source_path or not digest:
                continue
            candidate = Path(str(source_path)).expanduser()
            if not candidate.is_absolute():
                candidate = self.root / candidate
            if not candidate.is_file():
                stale.add(evidence_id)
                continue
            resolved = candidate.resolve()
            if resolved not in cache:
                cache[resolved] = _file_hash(resolved)
            if cache[resolved] != digest:
                stale.add(evidence_id)
        return stale

    def course_view(self, course_id: str) -> dict[str, Any]:
        course = self._course(course_id)
        assessments, standalone_deadlines, warnings, context = build_assessments(self.store, self.root, self.semester, str(course["id"]))
        evidence_map = self.store.evidence_map()
        stale_evidence_ids = self._stale_evidence_ids()
        public = []
        conflicts: list[dict[str, Any]] = []
        for assessment in assessments:
            links = self.store.list_links(assessment_id=assessment["id"])
            view = public_assessment(assessment, self._assertions_for(assessment["id"]), evidence_map, links, stale_evidence_ids)
            public.append(view)
            conflicts.extend(view["fields"]["due_date"].get("conflicts", []))
        schema = self.store.read_schema() if self.store.schema_path.exists() else {}
        return {
            "semester": self.semester,
            "course": context.get("course"),
            "assessments": public,
            "standalone_deadlines": standalone_deadlines,
            "conflicts": conflicts,
            "warnings": [*warnings, *schema.get("migration", {}).get("warnings", [])],
            "migration": schema.get("migration", {"status": "not_run"}),
        }

    def assessment_view(self, assessment_id: str, course_id: str | None = None) -> dict[str, Any]:
        assessments, _deadlines, warnings, _context = build_assessments(self.store, self.root, self.semester, course_id)
        selected = resolve_assessment(assessments, assessment_id)
        evidence_map = self.store.evidence_map()
        links = self.store.list_links(assessment_id=selected["id"])
        assertions = self._assertions_for(selected["id"])
        evidence_ids = {evidence_id for assertion in assertions for evidence_id in assertion.get("evidence_ids", [])}
        view = public_assessment(selected, assertions, evidence_map, links, self._stale_evidence_ids(evidence_ids))
        return {"assessment": view, "warnings": warnings}

    def conflicts(self, course_id: str) -> dict[str, Any]:
        view = self.course_view(course_id)
        conflicts = []
        for conflict in view.get("conflicts", []):
            item = dict(conflict)
            item.setdefault("available_actions", ["propose_change", "keep_current", "inspect_evidence"])
            conflicts.append(item)
        return {"semester": self.semester, "course": view.get("course"), "conflicts": conflicts, "warnings": view.get("warnings", [])}

    def links(self, course_id: str) -> dict[str, Any]:
        course = self._course(course_id)
        records = self.store.list_links()
        selected = []
        task_store = TaskStore(self.root, self.semester)
        for link in records:
            if str(link.get("course_id")) != str(course["id"]):
                continue
            item = dict(link)
            try:
                task = task_store.get(str(link.get("task_id")))
                item["task_title"] = task.get("title")
                item["task_due_date"] = task.get("due_date")
                item["task_status"] = task.get("status")
                item["diverged"] = bool(link.get("last_synced_due_date") and task.get("due_date") != link.get("last_synced_due_date"))
            except (KeyError, ValueError):
                item["task_title"] = None
                item["missing_task"] = True
            selected.append(item)
        return {"semester": self.semester, "course": course, "links": selected}

    # Migration

    def migrate(self, *, refresh: bool = False) -> dict[str, Any]:
        schema = self.store.ensure_schema(self.semester)
        migration = schema.setdefault("migration", {})
        source_hashes = migration.setdefault("source_hashes", {})
        aliases = migration.setdefault("aliases", [])
        warnings = migration.setdefault("warnings", [])
        created = 0
        refreshed = 0
        alias_seen = {sha256_json(item) for item in aliases if isinstance(item, dict)}
        semester_root = self.root / self.semester
        for course in course_records(semester_root):
            course_root = Path(str(course["path"]))
            assessments, _deadlines, course_warnings = build_course_assessments(self.store, self.root, self.semester, course_root)
            warnings.extend(item for item in course_warnings if item not in warnings)
            for assessment in assessments:
                if assessment.get("owner", {}).get("kind") == "assertion_only":
                    continue
                due_date = assessment.get("due_date")
                if due_date in {None, ""}:
                    continue
                owner = assessment["owner"]
                key = f"{owner.get('kind')}:{owner.get('locator')}:due_date"
                value_hash = sha256_json({"id": assessment["id"], "title": assessment["title"], "due_date": due_date})
                previous_hash = source_hashes.get(key)
                if previous_hash == value_hash:
                    continue
                applied_assertions = [
                    assertion for assertion in self.store.list_assertions(subject_id=assessment["id"], field="due_date", status="active")
                    if assertion.get("applied_change_id") and assertion.get("value") == due_date
                ]
                if previous_hash is not None and applied_assertions:
                    # The value changed through an approved ChangeSet, not an
                    # external edit. Advance the migration checkpoint without
                    # creating a false external_edit assertion.
                    source_hashes[key] = value_hash
                    continue
                source_kind = "legacy_record" if previous_hash is None else "external_edit"
                if source_kind == "external_edit":
                    refreshed += 1
                source_path = assessment.get("source", {}).get("path")
                source_file = self.root / source_path if source_path else None
                source_file_hash = _file_hash(source_file) if source_file and source_file.is_file() else None
                # The canonical history file is expected to change when a
                # student edits a record; use its hash for audit metadata, not
                # as an external-source freshness check.
                evidence_hash = source_file_hash if owner.get("kind") != "assignment_history" else None
                transition = value_hash if previous_hash is None else sha256_text(key + value_hash + str(previous_hash) + now())
                evidence_id = f"evidence:legacy:{transition[:24]}"
                assertion_id = f"assertion:legacy:{transition[:24]}"
                evidence = Evidence(
                    id=evidence_id,
                    source=str(assessment.get("source", {}).get("label") or "Legacy academic record"),
                    source_kind=source_kind,
                    source_path=source_path,
                    locator=str(assessment.get("source", {}).get("locator") or ""),
                    captured_at=now(),
                    sha256=evidence_hash,
                    provenance="USER-CREATED" if owner.get("kind") == "assignment_history" else "AI-GENERATED",
                    authority="local academic record",
                    verification="unverified",
                )
                assertion = Assertion(
                    id=assertion_id,
                    subject_type="assessment",
                    subject_id=assessment["id"],
                    subject_label=assessment["title"],
                    field="due_date",
                    value=due_date,
                    value_type="date",
                    source_kind=source_kind,
                    authority_scope=["assessment.due_date"],
                    specificity="exact",
                    verification="unverified",
                    confidence="likely" if owner.get("kind") == "assignment_history" else "unverified",
                    observed_at=now(),
                    created_at=now(),
                    created_by="system",
                    status="active",
                    evidence_ids=[evidence_id],
                    legacy={
                        "migration_key": key,
                        "record_basis": assessment.get("record_basis"),
                        "source_hash": source_file_hash,
                        "previous_value_hash": previous_hash,
                        "source_path": source_path,
                    },
                )
                try:
                    self.store.append_assertion(assertion, [evidence])
                    if source_kind == "external_edit":
                        self.store.activate_assertion(assertion.id, applied_change_id=None, supersede=True)
                    created += 1
                except ValueError as exc:
                    if "already exists" not in str(exc):
                        raise
                source_hashes[key] = value_hash
                for alias in assessment.get("aliases", []):
                    record = {
                        "assessment_id": assessment["id"],
                        "course_id": assessment["course_id"],
                        "kind": alias.get("kind"),
                        "entity_id": alias.get("entity_id"),
                        "title": alias.get("title"),
                        "value": alias.get("date") or alias.get("deadline"),
                    }
                    digest = sha256_json(record)
                    if digest not in alias_seen:
                        aliases.append(record)
                        alias_seen.add(digest)
        migration["status"] = "complete"
        migration["semester"] = self.semester
        migration["updated_at"] = now()
        migration["created_at"] = migration.get("created_at") or now()
        migration["warnings"] = warnings[-50:]
        self.store.write_schema(schema)
        if created or refreshed:
            self._activity().append(
                event_type="knowledge.migrated",
                title="Knowledge index updated",
                source=f"{self.semester}/.academia/knowledge",
                confidence="unverified",
                actor="system",
                details={"created_assertions": created, "refreshed_assertions": refreshed, "warnings": len(warnings)},
            )
        return {
            "status": "complete",
            "semester": self.semester,
            "created_assertions": created,
            "refreshed_assertions": refreshed,
            "warnings": warnings,
            "migration": migration,
        }

    def ensure_ready(self) -> None:
        if not self.store.schema_path.exists():
            self.migrate()
        else:
            schema = self.store.read_schema()
            if schema.get("migration", {}).get("status") != "complete":
                self.migrate()

    # Links

    def link_task(self, *, course_id: str, assessment_id: str, task_id: str, mode: str, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        self._require_user(actor, channel)
        if mode not in {"mirror_deadline", "related"}:
            raise ValueError("link mode must be mirror_deadline or related")
        self.ensure_ready()
        assessment, _assessments, _warnings = self._assessment(course_id, assessment_id)
        task_store = TaskStore(self.root, self.semester)
        task = task_store.get(task_id)
        task_course = str(task.get("course_id") or "")
        if task_course:
            try:
                task_course = str(resolve_course_identifier(course_records(self.root / self.semester), task_course)["id"])
            except (KeyError, ValueError):
                pass
        if task_course != str(assessment.get("course_id") or ""):
            raise ValueError("task and assessment must belong to the same course")
        if mode == "mirror_deadline" and task.get("due_date") != assessment.get("due_date"):
            raise ValueError("a mirror link requires the task due date to equal the assessment deadline")
        existing = next(
            (link for link in self.store.list_links(assessment_id=assessment["id"], task_id=str(task["id"])) if link.get("status") in {"active", "paused"}),
            None,
        )
        timestamp = now()
        if existing:
            link = TaskLink(
                id=str(existing["id"]),
                course_id=str(existing["course_id"]),
                assessment_id=str(existing["assessment_id"]),
                task_id=str(existing["task_id"]),
                mode=mode,
                status="active",
                created_at=str(existing.get("created_at") or timestamp),
                created_by=str(existing.get("created_by") or actor),
                updated_at=timestamp,
                updated_by=actor,
                last_synced_due_date=task.get("due_date") if mode == "mirror_deadline" else None,
                paused_by_change_id=None,
                note=existing.get("note"),
            )
            event_type = "knowledge.link.updated"
        else:
            link = TaskLink(
                id=new_id("link"),
                course_id=str(assessment["course_id"]),
                assessment_id=str(assessment["id"]),
                task_id=str(task["id"]),
                mode=mode,
                status="active",
                created_at=timestamp,
                created_by=actor,
                updated_at=timestamp,
                updated_by=actor,
                last_synced_due_date=task.get("due_date") if mode == "mirror_deadline" else None,
            )
            event_type = "knowledge.link.created"
        self.store.upsert_link(link)
        self._activity().append(
            event_type=event_type,
            title=f"Task link {'updated' if existing else 'created'}: {task.get('title')}",
            course=str(assessment.get("course_id") or ""),
            source=f"{self.semester}/SEMESTER_TASKS.md",
            confidence="user-confirmed",
            actor=actor,
            details={"link_id": link.id, "assessment_id": link.assessment_id, "task_id": link.task_id, "mode": link.mode},
        )
        return link.to_dict()

    def pause_link(self, *, link_id: str, actor: str = "user", channel: str = "cli_user", change_id: str | None = None) -> dict[str, Any]:
        if not (actor == "system" and channel == "internal" and change_id):
            self._require_user(actor, channel)
        existing = self.store.get_link(link_id)
        link = TaskLink.from_dict({
            **existing,
            "status": "paused",
            "updated_at": now(),
            "updated_by": actor,
            "paused_by_change_id": change_id or existing.get("paused_by_change_id"),
        })
        self.store.upsert_link(link)
        self._activity().append(
            event_type="knowledge.link.paused",
            title="Task deadline link paused",
            course=str(link.course_id),
            source=f"{self.semester}/SEMESTER_TASKS.md",
            confidence="user-confirmed",
            actor=actor,
            details={"link_id": link.id, "assessment_id": link.assessment_id, "task_id": link.task_id},
        )
        return link.to_dict()

    def resume_link(self, *, link_id: str, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        self._require_user(actor, channel)
        existing = self.store.get_link(link_id)
        if existing.get("mode") == "mirror_deadline":
            assessment, _assessments, _warnings = self._assessment(str(existing.get("course_id")), str(existing.get("assessment_id")))
            try:
                task = TaskStore(self.root, self.semester).get(str(existing.get("task_id")))
            except KeyError as exc:
                raise ValueError("the linked task no longer exists") from exc
            if task.get("due_date") != assessment.get("due_date"):
                raise ValueError("the task does not currently match the assessment deadline; move the task first or create a new change")
        link = TaskLink.from_dict({
            **existing,
            "status": "active",
            "updated_at": now(),
            "updated_by": actor,
            "paused_by_change_id": None,
        })
        self.store.upsert_link(link)
        self._activity().append(
            event_type="knowledge.link.resumed",
            title="Task deadline link resumed",
            course=str(link.course_id),
            source=f"{self.semester}/SEMESTER_TASKS.md",
            confidence="user-confirmed",
            actor=actor,
            details={"link_id": link.id, "assessment_id": link.assessment_id, "task_id": link.task_id},
        )
        return link.to_dict()

    # ChangeSet proposal

    def _supersede_open_proposals(self, assessment_id: str, *, actor: str, channel: str) -> None:
        for raw in self.store.list_changesets():
            if raw.get("status") not in {"proposed", "approved", "executing"}:
                continue
            assessment_operation = next(
                (
                    operation for operation in raw.get("operations", [])
                    if isinstance(operation, dict)
                    and operation.get("type") == "assessment.set_deadline"
                    and operation.get("target", {}).get("entity_id") == assessment_id
                ),
                None,
            )
            if assessment_operation is None:
                continue
            if raw.get("status") == "approved":
                raise ValueError("an approved change already exists for this assessment; apply or cancel it first")
            if raw.get("status") == "executing":
                raise ValueError("a change is already executing for this assessment; recover or wait for it to finish")
            changeset = ChangeSet.from_dict(raw)
            assertion_id = assessment_operation.get("target", {}).get("assertion_id")
            if assertion_id:
                try:
                    assertion = self.store.get_assertion(str(assertion_id))
                    if assertion.get("status") == "candidate":
                        self.store.reject_assertion(str(assertion_id), reason="superseded by a newer proposal", change_id=changeset.id)
                except KeyError:
                    pass
            changeset.status = "superseded"
            changeset.updated_at = now()
            self.store.save_changeset(changeset)
            self.store.append_event(
                changeset_id=changeset.id,
                event_type="changeset.superseded",
                actor=actor,
                channel=channel,
                details={"assessment_id": assessment_id},
            )

    def propose_deadline_change(
        self,
        *,
        course_id: str,
        assessment_id: str,
        new_date: str,
        source_kind: str = "student_report",
        source_label: str | None = None,
        evidence_path: str | None = None,
        evidence_locator: str | None = None,
        evidence_excerpt: str | None = None,
        note: str | None = None,
        actor: str = "user",
        channel: str = "cli_user",
    ) -> dict[str, Any]:
        if source_kind not in {"student_report", "professor_announcement", "original_document", "verified_external"}:
            raise ValueError("unsupported change source")
        self.ensure_ready()
        assessment, _assessments, assessment_warnings = self._assessment(course_id, assessment_id)
        if assessment.get("owner", {}).get("kind") == "assertion_only":
            raise ValueError("this assessment has no materialized academic record; create or import the assessment record before changing its deadline")
        before = assessment.get("due_date")
        if before in {None, ""}:
            raise ValueError("this assessment has no current deadline; add one in History before reporting a change")
        after = date_text(new_date, "new deadline")
        if before == after:
            raise ValueError("the proposed deadline already matches the recorded value")
        evidence_file = self._safe_evidence_path(evidence_path)
        if source_kind in {"original_document", "verified_external"} and evidence_file is None:
            raise ValueError("that source kind requires an evidence file so the claim can be checked")
        source_path = evidence_file.relative_to(self.root).as_posix() if evidence_file else None
        source_file_hash = _file_hash(evidence_file) if evidence_file else None
        label = source_label or {
            "student_report": "Student report",
            "professor_announcement": "Professor announcement",
            "original_document": evidence_file.name if evidence_file else "Original document",
            "verified_external": evidence_file.name if evidence_file else "Verified external source",
        }[source_kind]
        verification = "verified" if source_kind == "verified_external" else "unverified"
        confidence = "current-confirmed" if source_kind == "verified_external" else ("likely" if source_kind in {"student_report", "professor_announcement"} else "unverified")
        evidence = Evidence(
            id=new_id("evidence"),
            source=label,
            source_kind=source_kind,
            source_path=source_path,
            locator=evidence_locator,
            excerpt=evidence_excerpt,
            captured_at=now(),
            sha256=source_file_hash,
            provenance={
                "student_report": "USER-CREATED",
                "professor_announcement": "EXTERNAL",
                "original_document": "ORIGINAL",
                "verified_external": "EXTERNAL",
            }[source_kind],
            authority={
                "student_report": "student",
                "professor_announcement": "course instructor",
                "original_document": "course document",
                "verified_external": "verified external source",
            }[source_kind],
            verification=verification,
        )
        changeset_id = new_id("changeset")
        assertion = Assertion(
            id=new_id("assertion"),
            subject_type="assessment",
            subject_id=assessment["id"],
            subject_label=assessment["title"],
            field="due_date",
            value=after,
            value_type="date",
            source_kind=source_kind,
            authority_scope=["assessment.due_date"],
            specificity="exact",
            verification=verification,
            confidence=confidence,
            observed_at=now(),
            created_at=now(),
            created_by=actor,
            status="candidate",
            evidence_ids=[evidence.id],
            metadata={"note": note, "proposed_change_id": changeset_id} if note else {"proposed_change_id": changeset_id},
        )
        self._supersede_open_proposals(assessment["id"], actor=actor, channel=channel)
        self.store.append_assertion(assertion, [evidence])

        assessment_operation_id = new_id("op")
        assessment_operation = Operation(
            id=assessment_operation_id,
            type="assessment.set_deadline",
            target={
                "entity_type": "assessment",
                "entity_id": assessment["id"],
                "owner_kind": assessment["owner"]["kind"],
                "owner_locator": assessment["owner"].get("locator"),
                "field": "due_date",
                "assertion_id": assertion.id,
            },
            before=before,
            after=after,
            required=True,
            default_selected=True,
            reversible=True,
            expected_revision=assessment_revision(assessment),
            idempotency_key="",
            evidence_ids=[evidence.id],
            label="Assessment deadline",
            target_title=assessment["title"],
        )
        assessment_operation.idempotency_key = _operation_key(changeset_id, assessment_operation)
        operations = [assessment_operation]
        warnings = [*assessment_warnings]
        task_store = TaskStore(self.root, self.semester)
        for link in self.store.list_links(assessment_id=assessment["id"], status="active"):
            if link.get("mode") != "mirror_deadline":
                continue
            try:
                task = task_store.get(str(link.get("task_id")))
            except (KeyError, ValueError):
                warnings.append(f"A linked task no longer exists: {link.get('task_id')}. Its link was left unchanged.")
                continue
            if task.get("status") in {"done", "cancelled"}:
                warnings.append(f"Linked task {task.get('title')} is {task.get('status')} and was not included.")
                continue
            task_course = str(task.get("course_id") or "")
            if task_course:
                try:
                    task_course = str(resolve_course_identifier(course_records(self.root / self.semester), task_course)["id"])
                except (KeyError, ValueError):
                    pass
            if task_course != str(assessment.get("course_id") or ""):
                warnings.append(f"Linked task {task.get('title')} belongs to another course and was not included.")
                continue
            if task.get("due_date") != before:
                warnings.append(
                    f"Linked task {task.get('title')} no longer mirrors this deadline (task {task.get('due_date') or 'has no date'}, assessment {before}). It was not changed."
                )
                continue
            operation_id = new_id("op")
            operation = Operation(
                id=operation_id,
                type="task.set_due",
                target={
                    "entity_type": "task",
                    "entity_id": str(task["id"]),
                    "field": "due_date",
                    "link_id": link["id"],
                },
                before=task.get("due_date"),
                after=after,
                depends_on=[assessment_operation_id],
                required=False,
                default_selected=True,
                reversible=True,
                sync_basis="mirror_deadline",
                skip_effect="pause_link",
                expected_revision=_task_revision(task),
                idempotency_key="",
                evidence_ids=[evidence.id],
                label="Task deadline",
                target_title=str(task.get("title") or task["id"]),
            )
            operation.idempotency_key = _operation_key(changeset_id, operation)
            operations.append(operation)
        evidence_map = self.store.evidence_map()
        assertions = self._assertions_for(assessment["id"])
        evidence_ids = {evidence_id for assertion in assertions for evidence_id in assertion.get("evidence_ids", [])}
        resolved = resolve_field(assessment, "due_date", assertions, evidence_map, self._stale_evidence_ids(evidence_ids))
        warnings.extend(warning for warning in resolved.get("warnings", []) if warning not in warnings)
        conflicts = [dict(conflict) for conflict in resolved.get("conflicts", [])]
        conflicts.append({
            "id": f"conflict:{assessment['id']}:due_date:proposed",
            "kind": "proposed_value_differs_from_record",
            "subject": {"type": "assessment", "id": assessment["id"]},
            "field": "due_date",
            "owner_value": before,
            "assertion_value": after,
            "assertion_id": assertion.id,
            "source_kind": source_kind,
            "verification": verification,
            "confidence": confidence,
            "evidence": [evidence.to_dict()],
            "why": f"The canonical record says {before}, and this {source_kind.replace('_', ' ')} says {after}.",
            "resolution": "needs_confirmation",
        })
        optional_ids = [operation.id for operation in operations if not operation.required]
        affected = [{"type": "assessment", "id": assessment["id"], "title": assessment["title"]}]
        affected.extend({"type": "task", "id": operation.target["entity_id"], "title": operation.target_title} for operation in operations if operation.type == "task.set_due")
        changeset = ChangeSet(
            id=changeset_id,
            version=1,
            title=f"Move {assessment['title']} deadline to {after}",
            course_id=str(assessment["course_id"]),
            semester=self.semester,
            origin="agent_request" if actor.startswith(AGENT_ACTOR_PREFIX) else "student_request",
            status="proposed",
            created_at=now(),
            updated_at=now(),
            created_by=actor,
            summary=f"Update the assessment deadline from {before} to {after}" + (f" and {len(optional_ids)} mirrored task deadline{'s' if len(optional_ids) != 1 else ''}." if optional_ids else "."),
            evidence_ids=[evidence.id],
            operations=operations,
            conflicts=conflicts,
            warnings=warnings,
            impact={
                "required_operations": [assessment_operation_id],
                "optional_operations": optional_ids,
                "irreversible_operations": [],
                "affected_entities": affected,
                "summary": "1 assessment" + (f" and {len(optional_ids)} mirrored task{'s' if len(optional_ids) != 1 else ''}" if optional_ids else ""),
            },
            approval={
                "status": "pending",
                "mode": None,
                "approved_operation_ids": [],
                "approved_by": None,
                "approved_at": None,
                "channel": None,
                "version": None,
                "approval_hash": None,
                "note": note,
            },
            execution={
                "journal_id": changeset_id,
                "started_at": None,
                "completed_at": None,
                "last_actor": None,
                "attempts": 0,
            },
            result={"state": "not_started", "operation_results": [], "summary": None},
            reversal={"status": "not_requested", "requested_at": None, "approved_by": None, "completed_at": None, "operation_results": []},
        )
        self.store.save_changeset(changeset)
        self.store.append_event(changeset_id=changeset.id, event_type="changeset.created", actor=actor, channel=channel)
        self.store.append_event(changeset_id=changeset.id, event_type="changeset.proposed", actor=actor, channel=channel, details={"version": 1})
        self._activity().append(
            event_type="knowledge.change.proposed",
            title=changeset.title,
            course=changeset.course_id,
            source=f"{self.semester}/.academia/knowledge/change_journal.json",
            confidence="unverified",
            actor=actor,
            details={"changeset_id": changeset.id, "operations": len(operations), "before": before, "after": after},
        )
        return self.get_changeset(changeset.id)

    # ChangeSet lifecycle

    def get_changeset(self, changeset_id: str) -> dict[str, Any]:
        value = self.store.get_changeset(changeset_id)
        evidence_map = self.store.evidence_map()
        evidence_ids = set(value.get("evidence_ids", []))
        for operation in value.get("operations", []):
            evidence_ids.update(operation.get("evidence_ids", []))
        value["evidence"] = [evidence_map[item] for item in sorted(evidence_ids) if item in evidence_map]
        return value

    def list_changesets(self, *, course_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        values = []
        for item in self.store.list_changesets():
            if course_id is not None and item.get("course_id") != course_id:
                continue
            if status is not None and item.get("status") != status:
                continue
            values.append(self.get_changeset(str(item["id"])))
        values.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return {"semester": self.semester, "changesets": values}

    def approve_changeset(
        self,
        changeset_id: str,
        *,
        operation_ids: list[str] | None = None,
        actor: str = "user",
        channel: str = "cli_user",
        note: str | None = None,
    ) -> dict[str, Any]:
        self._require_user(actor, channel)
        raw = self.store.get_changeset(changeset_id)
        changeset = ChangeSet.from_dict(raw)
        if changeset.status != "proposed":
            raise ValueError(f"changeset is not awaiting approval: {changeset.status}")
        by_id = {operation.id: operation for operation in changeset.operations}
        defaults = [operation.id for operation in changeset.operations if operation.required or operation.default_selected]
        selected = defaults if operation_ids is None else list(dict.fromkeys(operation_ids))
        if not selected:
            raise ValueError("select at least one operation")
        unknown = [operation_id for operation_id in selected if operation_id not in by_id]
        if unknown:
            raise ValueError(f"unknown operation: {unknown[0]}")
        required_missing = [operation.id for operation in changeset.operations if operation.required and operation.id not in selected]
        if required_missing:
            raise ValueError("the required assessment deadline operation must be approved")
        changeset.approval = {
            "status": "approved",
            "mode": "full" if len(selected) == len(changeset.operations) else "partial",
            "approved_operation_ids": selected,
            "approved_by": actor,
            "approved_at": now(),
            "channel": channel,
            "version": changeset.version,
            "approval_hash": approval_hash(changeset),
            "note": note if note is not None else changeset.approval.get("note"),
        }
        changeset.status = "approved"
        changeset.updated_at = now()
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="changeset.approved",
            actor=actor,
            channel=channel,
            details={"operations": selected, "mode": changeset.approval["mode"]},
        )
        self._activity().append(
            event_type="knowledge.change.approved",
            title=changeset.title,
            course=changeset.course_id,
            source=f"{self.semester}/.academia/knowledge/change_journal.json",
            confidence="unverified",
            actor=actor,
            details={"changeset_id": changeset.id, "operations": selected, "mode": changeset.approval["mode"]},
        )
        return self.get_changeset(changeset.id)

    def execute_changeset(self, changeset_id: str, *, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        from .executor import ChangeExecutor

        return ChangeExecutor(self).execute(changeset_id, actor=actor, channel=channel)

    def retry_changeset(self, changeset_id: str, *, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        raw = self.store.get_changeset(changeset_id)
        if raw.get("status") not in {"failed", "partially_applied"}:
            raise ValueError(f"changeset has no failed operations to retry: {raw.get('status')}")
        from .executor import ChangeExecutor

        return ChangeExecutor(self).execute(changeset_id, actor=actor, channel=channel, retry=True)

    def amend_deadline_change(
        self,
        changeset_id: str,
        *,
        new_date: str | None = None,
        note: str | None = None,
        actor: str = "user",
        channel: str = "cli_user",
    ) -> dict[str, Any]:
        self._require_user(actor, channel)
        if new_date is None and note is None:
            raise ValueError("provide a new date or a note to amend the proposal")
        changeset = ChangeSet.from_dict(self.store.get_changeset(changeset_id))
        if changeset.status not in {"proposed", "approved"}:
            raise ValueError(f"changeset cannot be amended from {changeset.status}")
        if any(operation.status in {"verified", "executing"} for operation in changeset.operations):
            raise ValueError("a changeset with executed operations cannot be amended")
        assessment_operation = next((operation for operation in changeset.operations if operation.type == "assessment.set_deadline"), None)
        if assessment_operation is None:
            raise ValueError("changeset has no assessment deadline operation")
        assessment, _assessments, _warnings = self._assessment(changeset.course_id, str(assessment_operation.target["entity_id"]))
        old_assertion_id = str(assessment_operation.target.get("assertion_id") or "")
        evidence_ids = list(assessment_operation.evidence_ids)
        if new_date is not None:
            after = date_text(new_date, "new deadline")
            if after != assessment_operation.after:
                if after == assessment_operation.before:
                    raise ValueError("the amended deadline matches the recorded value")
                try:
                    old_assertion = self.store.get_assertion(old_assertion_id)
                except KeyError:
                    old_assertion = {}
                if old_assertion.get("status") == "candidate":
                    self.store.reject_assertion(old_assertion_id, reason="replaced by amendment", change_id=changeset.id)
                source_kind = str(old_assertion.get("source_kind") or "student_report")
                if source_kind not in {"student_report", "professor_announcement", "original_document", "verified_external"}:
                    source_kind = "student_report"
                verification = str(old_assertion.get("verification") or "unverified")
                confidence = str(old_assertion.get("confidence") or "likely")
                metadata = dict(old_assertion.get("metadata") or {})
                metadata["proposed_change_id"] = changeset.id
                metadata["amended_from"] = old_assertion_id
                if note is not None:
                    metadata["note"] = note
                assertion = Assertion(
                    id=new_id("assertion"),
                    subject_type="assessment",
                    subject_id=str(assessment["id"]),
                    subject_label=assessment.get("title"),
                    field="due_date",
                    value=after,
                    value_type="date",
                    source_kind=source_kind,
                    authority_scope=["assessment.due_date"],
                    specificity="exact",
                    verification=verification,
                    confidence=confidence,
                    observed_at=now(),
                    created_at=now(),
                    created_by=actor,
                    status="candidate",
                    evidence_ids=evidence_ids,
                    metadata=metadata,
                )
                self.store.append_assertion(assertion)
                assessment_operation.after = after
                assessment_operation.target["assertion_id"] = assertion.id
                assessment_operation.expected_revision = assessment_revision(assessment)
                assessment_operation.idempotency_key = _operation_key(changeset.id, assessment_operation)
                evidence_ids = list(assertion.evidence_ids)
                updated_conflicts = []
                matched = False
                for conflict in changeset.conflicts:
                    item = dict(conflict)
                    if item.get("assertion_id") == old_assertion_id:
                        matched = True
                        item["assertion_id"] = assertion.id
                        item["assertion_value"] = after
                        item["source_kind"] = source_kind
                        item["verification"] = verification
                        item["confidence"] = confidence
                        item["why"] = f"The canonical record says {assessment_operation.before}, and this {source_kind.replace('_', ' ')} says {after}."
                    updated_conflicts.append(item)
                if not matched:
                    updated_conflicts.append({
                        "id": f"conflict:{assessment['id']}:due_date:proposed",
                        "kind": "proposed_value_differs_from_record",
                        "subject": {"type": "assessment", "id": assessment["id"]},
                        "field": "due_date",
                        "owner_value": assessment_operation.before,
                        "assertion_value": after,
                        "assertion_id": assertion.id,
                        "source_kind": source_kind,
                        "verification": verification,
                        "confidence": confidence,
                        "why": f"The canonical record says {assessment_operation.before}, and this {source_kind.replace('_', ' ')} says {after}.",
                        "resolution": "needs_confirmation",
                    })
                changeset.conflicts = updated_conflicts
                changeset.title = f"Move {assessment['title']} deadline to {after}"
                changeset.summary = f"Update the assessment deadline from {assessment_operation.before} to {after}."
                task_store = TaskStore(self.root, self.semester)
                for operation in changeset.operations:
                    if operation.type != "task.set_due":
                        continue
                    task = task_store.get(str(operation.target["entity_id"]))
                    operation.after = after
                    operation.expected_revision = _task_revision(task)
                    operation.idempotency_key = _operation_key(changeset.id, operation)
                    operation.evidence_ids = evidence_ids
        if note is not None:
            changeset.title = f"Move {assessment['title']} deadline to {assessment_operation.after}"
        changeset.version += 1
        changeset.status = "proposed"
        changeset.approval = {
            "status": "pending",
            "mode": None,
            "approved_operation_ids": [],
            "approved_by": None,
            "approved_at": None,
            "channel": None,
            "version": None,
            "approval_hash": None,
            "note": note if note is not None else changeset.approval.get("note"),
        }
        changeset.updated_at = now()
        self.store.save_changeset(changeset)
        self.store.append_event(
            changeset_id=changeset.id,
            event_type="changeset.amended",
            actor=actor,
            channel=channel,
            details={"version": changeset.version, "after": assessment_operation.after},
        )
        return self.get_changeset(changeset.id)

    def cancel_changeset(self, changeset_id: str, *, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        self._require_user(actor, channel)
        changeset = ChangeSet.from_dict(self.store.get_changeset(changeset_id))
        if changeset.status not in {"proposed", "approved"}:
            raise ValueError(f"changeset cannot be cancelled from {changeset.status}")
        if any(operation.status in {"verified", "executing"} for operation in changeset.operations):
            raise ValueError("a changeset with executed operations cannot be cancelled")
        changeset.status = "cancelled"
        changeset.updated_at = now()
        for operation in changeset.operations:
            assertion_id = operation.target.get("assertion_id") if operation.type == "assessment.set_deadline" else None
            if assertion_id:
                try:
                    assertion = self.store.get_assertion(str(assertion_id))
                    if assertion.get("status") == "candidate":
                        self.store.reject_assertion(str(assertion_id), reason="changeset cancelled", change_id=changeset.id)
                except KeyError:
                    pass
        self.store.save_changeset(changeset)
        self.store.append_event(changeset_id=changeset.id, event_type="changeset.cancelled", actor=actor, channel=channel)
        return self.get_changeset(changeset.id)

    def reverse_changeset(self, changeset_id: str, *, actor: str = "user", channel: str = "cli_user") -> dict[str, Any]:
        self._require_user(actor, channel)
        from .executor import ChangeExecutor

        return ChangeExecutor(self).reverse(changeset_id, actor=actor, channel=channel)

    def recover_incomplete(self) -> dict[str, Any]:
        from .executor import ChangeExecutor

        return ChangeExecutor(self).recover()

    # Internal helpers used by the executor

    def task_store(self) -> TaskStore:
        return TaskStore(self.root, self.semester)

    def domain(self) -> DomainProjection:
        return DomainProjection(self.root / ".academia" / "domain.json")

    def update_history_deadline(self, *, course_id: str, record_id: str, before: str, after: str, actor: str) -> dict[str, Any]:
        return update_assignment_history(
            self.root,
            self.semester,
            course_id,
            record_id,
            {"due_date": after},
            actor=actor,
            expected_due_date=before,
        )

    def apply_assertion(self, assertion_id: str, *, changeset_id: str) -> None:
        try:
            self.store.activate_assertion(assertion_id, applied_change_id=changeset_id, supersede=True)
        except KeyError:
            return

    def record_reversal_assertion(self, operation: Operation, *, changeset_id: str) -> None:
        assertion_id = operation.target.get("assertion_id")
        if not assertion_id:
            return
        try:
            original = self.store.get_assertion(str(assertion_id))
        except KeyError:
            return
        for existing in self.store.list_assertions(subject_id=str(original.get("subject_id")), field=str(original.get("field") or "due_date")):
            metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
            if metadata.get("reversed_change_id") == changeset_id and existing.get("value") == operation.before and existing.get("status") == "active":
                return
        restored = Assertion(
            id=new_id("assertion"),
            subject_type=str(original.get("subject_type") or "assessment"),
            subject_id=str(original.get("subject_id")),
            subject_label=original.get("subject_label"),
            field=str(original.get("field") or "due_date"),
            value=operation.before,
            value_type=str(original.get("value_type") or "date"),
            source_kind="system_projection",
            authority_scope=list(original.get("authority_scope", ["assessment.due_date"])),
            specificity="exact",
            verification="unverified",
            confidence="likely",
            observed_at=now(),
            created_at=now(),
            created_by="system",
            status="active",
            applied_change_id=changeset_id,
            evidence_ids=list(original.get("evidence_ids", [])),
            metadata={"reversed_change_id": changeset_id, "reversal": True},
        )
        self.store.append_assertion(restored)
        self.store.activate_assertion(restored.id, applied_change_id=changeset_id, supersede=True)

    def apply_skip_effect(self, changeset_id: str, operation: Operation, actor: str, channel: str) -> None:
        if operation.skip_effect == "pause_link":
            link_id = operation.target.get("link_id")
            if link_id:
                self.pause_link(link_id=str(link_id), actor="system", channel="internal", change_id=changeset_id)


def _operation_key(changeset_id: str, operation: Operation) -> str:
    return "sha256:" + sha256_json({
        "changeset_id": changeset_id,
        "operation_id": operation.id,
        "type": operation.type,
        "target": operation.target,
        "before": operation.before,
        "after": operation.after,
        "expected_revision": operation.expected_revision,
    })
