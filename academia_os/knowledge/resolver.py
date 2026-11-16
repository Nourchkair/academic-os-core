"""Build academic assessment views and resolve field-level effective values."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..assignment_history import HISTORY_FILENAME, HISTORY_RELATIVE_PATH, list_assignment_history
from ..course_identity import course_code, course_records, resolve_course_identifier
from ..domain import DomainProjection
from .model import normalize, sha256_json
from .store import KnowledgeStore

SOURCE_AUTHORITY: dict[str, int] = {
    "professor_announcement": 5,
    "verified_external": 5,
    "original_document": 4,
    "external_edit": 3,
    "student_report": 3,
    "legacy_record": 2,
    "ai_extraction": 1,
    "system_projection": 0,
}
VERIFICATION_RANK: dict[str, int] = {
    "verified": 3,
    "corroborated": 2,
    "unverified": 1,
    "disputed": 0,
}
SPECIFICITY_RANK: dict[str, int] = {
    "exact": 3,
    "partial": 2,
    "approximate": 1,
    "unknown": 0,
}
FIELD_ALIASES = {"due_date": "due_date", "deadline": "due_date", "weight": "weight"}


def _timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def scope_matches(authority_scope: Iterable[str], field: str) -> bool:
    for raw in authority_scope:
        scope = str(raw).strip()
        if not scope:
            continue
        if scope in {"*", field}:
            return True
        if scope.endswith(".*") and field.startswith(scope[:-1]):
            return True
    return False


def assertion_rank(assertion: dict[str, Any]) -> tuple[int, int, int, float]:
    return (
        SOURCE_AUTHORITY.get(str(assertion.get("source_kind")), 0),
        VERIFICATION_RANK.get(str(assertion.get("verification")), 0),
        SPECIFICITY_RANK.get(str(assertion.get("specificity")), 0),
        _timestamp(assertion.get("published_at") or assertion.get("observed_at") or assertion.get("created_at")),
    )


def assertion_summary(assertion: dict[str, Any]) -> dict[str, Any]:
    return {
        "assertion_id": assertion.get("id"),
        "value": assertion.get("value"),
        "source_kind": assertion.get("source_kind"),
        "verification": assertion.get("verification"),
        "confidence": assertion.get("confidence"),
        "specificity": assertion.get("specificity"),
        "observed_at": assertion.get("observed_at"),
        "published_at": assertion.get("published_at"),
        "applied_change_id": assertion.get("applied_change_id"),
        "evidence_ids": list(assertion.get("evidence_ids", [])),
    }


def field_value(assessment: dict[str, Any], field: str) -> Any:
    selected = FIELD_ALIASES.get(field, field)
    if selected == "due_date":
        return assessment.get("due_date")
    return assessment.get(selected)


def assessment_revision(assessment: dict[str, Any], field: str = "due_date") -> str:
    selected = FIELD_ALIASES.get(field, field)
    return "sha256:" + sha256_json({"id": assessment.get("id"), "field": selected, "value": field_value(assessment, selected)})


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _history_path(course_root: Path) -> Path:
    return course_root / HISTORY_RELATIVE_PATH


def _history_assessment(root: Path, course_root: Path, semester: str, record: dict[str, Any]) -> dict[str, Any]:
    record_id = str(record.get("id"))
    assessment_id = f"assessment:history:{record_id}"
    path = _history_path(course_root)
    return {
        "id": assessment_id,
        "course_id": course_root.name,
        "course_name": course_root.name,
        "semester": semester,
        "title": str(record.get("title") or "Untitled coursework"),
        "kind": str(record.get("kind") or "assignment"),
        "status": record.get("status"),
        "owner": {
            "kind": "assignment_history",
            "record_id": record_id,
            "locator": f"{_relative(root, path)}#{record_id}",
            "field": "due_date",
        },
        "due_date": record.get("due_date"),
        "weight": record.get("weight"),
        "record_basis": record.get("record_basis"),
        "task_title": record.get("task_title"),
        "source": {
            "path": _relative(root, path),
            "locator": f"record:{record_id}",
            "label": "Assignment_History.json",
        },
        "aliases": [],
        "external_values": [],
        "warnings": [],
    }


def _domain_assessment(root: Path, semester: str, entity: dict[str, Any], *, course_id: str, warning: str | None = None) -> dict[str, Any]:
    entity_id = str(entity.get("id"))
    assessment_id = f"assessment:domain:{entity_id}"
    evidence = entity.get("evidence") if isinstance(entity.get("evidence"), dict) else {}
    raw_source_path = evidence.get("source_path")
    source_path = None
    if raw_source_path:
        candidate = Path(str(raw_source_path)).expanduser()
        source_path = _relative(root, candidate) if candidate.is_absolute() else str(raw_source_path)
    return {
        "id": assessment_id,
        "course_id": course_id,
        "course_name": course_id,
        "semester": semester,
        "title": str(entity.get("title") or "Untitled assessment"),
        "kind": "assignment",
        "status": entity.get("status"),
        "owner": {
            "kind": "domain_projection",
            "entity_id": entity_id,
            "locator": f".academia/domain.json#{entity_id}",
            "field": "deadline",
        },
        "due_date": entity.get("deadline"),
        "weight": entity.get("weight"),
        "record_basis": evidence.get("confidence"),
        "task_title": None,
        "source": {
            "path": source_path or ".academia/domain.json",
            "locator": evidence.get("source_location") or f"assignment:{entity_id}",
            "label": evidence.get("source") or "Extracted assessment",
        },
        "aliases": [],
        "external_values": [],
        "warnings": [warning] if warning else [],
    }


def _alias_value(assessment: dict[str, Any], *, source_kind: str, source: str, locator: str, value: Any) -> None:
    if value in {None, ""}:
        return
    assessment["external_values"].append({
        "source_kind": source_kind,
        "source": source,
        "locator": locator,
        "value": value,
    })


def build_course_assessments(store: KnowledgeStore, root: Path, semester: str, course_root: Path, *, include_unassigned_assertions: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (assessments, standalone deadlines, warnings) for one course."""
    warnings: list[str] = []
    assessments: list[dict[str, Any]] = []
    by_title: dict[str, list[dict[str, Any]]] = {}
    history_path = _history_path(course_root)
    if history_path.is_file():
        try:
            records = list_assignment_history(root, semester, course_root.name)
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not read {HISTORY_FILENAME}: {exc}")
            records = []
        for record in records:
            assessment = _history_assessment(root, course_root, semester, record)
            assessments.append(assessment)
            by_title.setdefault(normalize(assessment["title"]), []).append(assessment)

    domain = DomainProjection(root / ".academia" / "domain.json")
    course_keys = {normalize(course_root.name), normalize(course_code(course_root.name))}
    domain_assignments = [
        entity for entity in domain.list("assignment")
        if normalize(entity.get("course_id")) in course_keys or str(entity.get("course_id") or "") == course_root.name
    ]
    for entity in domain_assignments:
        title_key = normalize(entity.get("title"))
        matches = by_title.get(title_key, [])
        if len(matches) == 1:
            assessment = matches[0]
            assessment["aliases"].append({
                "kind": "domain_assignment",
                "entity_id": entity.get("id"),
                "title": entity.get("title"),
                "deadline": entity.get("deadline"),
                "status": entity.get("status"),
            })
            _alias_value(
                assessment,
                source_kind="legacy_record",
                source="Extracted domain projection",
                locator=f"assignment:{entity.get('id')}",
                value=entity.get("deadline"),
            )
            if entity.get("deadline") and assessment.get("due_date") and entity.get("deadline") != assessment.get("due_date"):
                warnings.append(
                    f"{assessment['title']}: the extracted assessment deadline {entity.get('deadline')} disagrees with the recorded deadline {assessment.get('due_date')}."
                )
            continue
        if len(matches) > 1:
            warnings.append(
                f"Ambiguous assessment identity for {entity.get('title')}: multiple history records share this title. No alias was created."
            )
            assessment = _domain_assessment(root, semester, entity, course_id=course_root.name, warning="This assessment has an ambiguous history match; no automatic merge was performed.")
        else:
            assessment = _domain_assessment(root, semester, entity, course_id=course_root.name)
        assessments.append(assessment)
        by_title.setdefault(title_key, []).append(assessment)

    # Domain deadline projections are aliases, never a second owner of an assessment.
    standalone_deadlines: list[dict[str, Any]] = []
    for entity in domain.list("deadline"):
        if normalize(entity.get("course_id")) not in course_keys and str(entity.get("course_id") or "") != course_root.name:
            continue
        title_key = normalize(entity.get("title"))
        matches = by_title.get(title_key, [])
        if len(matches) == 1:
            assessment = matches[0]
            assessment["aliases"].append({
                "kind": "deadline_projection",
                "entity_id": entity.get("id"),
                "title": entity.get("title"),
                "date": entity.get("date"),
                "type": entity.get("type"),
            })
            _alias_value(
                assessment,
                source_kind="legacy_record",
                source="Extracted deadline projection",
                locator=f"deadline:{entity.get('id')}",
                value=entity.get("date"),
            )
            if entity.get("date") and assessment.get("due_date") and entity.get("date") != assessment.get("due_date"):
                warnings.append(
                    f"{assessment['title']}: the extracted deadline {entity.get('date')} disagrees with the assessment deadline {assessment.get('due_date')}."
                )
            continue
        standalone_deadlines.append({
            "id": f"deadline:{entity.get('id')}",
            "course_id": entity.get("course_id"),
            "title": entity.get("title"),
            "date": entity.get("date"),
            "time": entity.get("time"),
            "type": entity.get("type"),
            "owner": {"kind": "domain_projection", "entity_id": entity.get("id"), "field": "date"},
            "source": {"path": ".academia/domain.json", "locator": f"deadline:{entity.get('id')}"},
        })

    # Assertion-only assessments have no materialized owner yet.
    known = {assessment["id"] for assessment in assessments}
    assertion_subjects: dict[str, dict[str, Any]] = {}
    for assertion in store.list_assertions(subject_type="assessment", status="active"):
        subject_id = str(assertion.get("subject_id"))
        if subject_id in known or subject_id.startswith("assessment:history:") or subject_id.startswith("assessment:domain:"):
            continue
        metadata = assertion.get("metadata") if isinstance(assertion.get("metadata"), dict) else {}
        assertion_course = metadata.get("course_id") if isinstance(metadata, dict) else None
        if assertion_course:
            if normalize(assertion_course) not in course_keys and str(assertion_course) != course_root.name:
                continue
        elif not include_unassigned_assertions:
            continue
        assertion_subjects.setdefault(subject_id, assertion)
    for subject_id, assertion in assertion_subjects.items():
        assessments.append({
            "id": subject_id,
            "course_id": course_root.name,
            "course_name": course_root.name,
            "semester": semester,
            "title": str(assertion.get("subject_label") or subject_id),
            "kind": "other",
            "status": None,
            "owner": {"kind": "assertion_only", "locator": None, "field": "due_date"},
            "due_date": None,
            "weight": None,
            "record_basis": None,
            "task_title": None,
            "source": {"path": None, "locator": None, "label": "Assertion only"},
            "aliases": [],
            "external_values": [],
            "warnings": ["No materialized academic record exists for this assessment yet."],
        })

    return assessments, standalone_deadlines, warnings


def build_assessments(store: KnowledgeStore, root: Path, semester: str, course_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    semester_root = root / semester
    if not semester_root.is_dir():
        raise KeyError(f"semester not found: {semester}")
    courses = course_records(semester_root)
    if course_id:
        selected = resolve_course_identifier(courses, course_id)
        courses = [selected]
    all_assessments: list[dict[str, Any]] = []
    all_deadlines: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    for index, course in enumerate(courses):
        assessments, deadlines, warnings = build_course_assessments(
            store,
            root,
            semester,
            Path(str(course["path"])),
            include_unassigned_assertions=(course_id is None and index == 0),
        )
        all_assessments.extend(assessments)
        all_deadlines.extend(deadlines)
        all_warnings.extend(warnings)
    # Assertion-only subjects are discovered per course; keep one logical
    # assessment when the caller did not narrow the semester view.
    unique_assessments: dict[str, dict[str, Any]] = {}
    for assessment in all_assessments:
        unique_assessments.setdefault(str(assessment["id"]), assessment)
    all_assessments = list(unique_assessments.values())
    course_value = None
    if course_id:
        selected = courses[0]
        course_value = {"id": selected["id"], "code": selected["code"], "name": selected["name"], "path": selected["path"]}
    return all_assessments, all_deadlines, all_warnings, {"course": course_value, "courses": courses}


def resolve_assessment(assessments: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    requested = str(identifier or "").strip()
    if not requested:
        raise ValueError("assessment identifier is required")
    exact = [assessment for assessment in assessments if assessment["id"] == requested]
    if exact:
        return exact[0]
    underlying = [
        assessment for assessment in assessments
        if str(assessment.get("owner", {}).get("record_id") or assessment.get("owner", {}).get("entity_id")) == requested
    ]
    if len(underlying) == 1:
        return underlying[0]
    if len(underlying) > 1:
        raise ValueError(f"assessment identifier is ambiguous: {identifier}")
    title_matches = [assessment for assessment in assessments if normalize(assessment["title"]) == normalize(requested)]
    if len(title_matches) == 1:
        return title_matches[0]
    if len(title_matches) > 1:
        raise ValueError(f"assessment identifier is ambiguous: {identifier}")
    raise KeyError(f"assessment not found: {identifier}")


def _evidence_list(assertion: dict[str, Any], evidence_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for evidence_id in assertion.get("evidence_ids", []):
        evidence = evidence_map.get(str(evidence_id))
        if evidence is not None:
            result.append(dict(evidence))
    return result


def _owner_source(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": assessment.get("source", {}).get("label"),
        "path": assessment.get("source", {}).get("path"),
        "locator": assessment.get("source", {}).get("locator"),
        "source_kind": "legacy_record",
        "verification": "unverified",
        "confidence": "likely" if assessment.get("owner", {}).get("kind") == "assignment_history" else "unverified",
        "record_basis": assessment.get("record_basis"),
    }


def _resolved_source(assessment: dict[str, Any], lead: dict[str, Any] | None, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    owner = _owner_source(assessment)
    if lead is None:
        return owner
    evidence = evidence_items[0] if evidence_items else {}
    return {
        **owner,
        "label": lead.get("source_kind") or owner.get("label"),
        "path": evidence.get("source_path") or owner.get("path"),
        "locator": evidence.get("locator") or owner.get("locator"),
        "source_kind": lead.get("source_kind"),
        "verification": lead.get("verification"),
        "confidence": lead.get("confidence"),
    }


def resolve_field(
    assessment: dict[str, Any],
    field: str,
    assertions: list[dict[str, Any]],
    evidence_map: dict[str, dict[str, Any]],
    stale_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    selected = FIELD_ALIASES.get(field, field)
    stale_evidence_ids = stale_evidence_ids or set()
    owner_value = field_value(assessment, selected)
    active = [assertion for assertion in assertions if assertion.get("status") == "active" and scope_matches(assertion.get("authority_scope", []), f"assessment.{selected}")]
    applied = [assertion for assertion in active if assertion.get("applied_change_id")]
    conflicts: list[dict[str, Any]] = []
    warnings: list[str] = list(assessment.get("warnings", []))

    if owner_value not in {None, ""}:
        disagreeing = [assertion for assertion in active if assertion.get("value") != owner_value]
        applied_mismatch = [assertion for assertion in applied if assertion.get("value") != owner_value]
        agreeing = [assertion for assertion in active if assertion.get("value") == owner_value]
        agreeing.sort(key=assertion_rank, reverse=True)
        lead = agreeing[0] if agreeing else None
        if applied_mismatch:
            resolution = "inconsistent"
            warnings.append("An applied assertion no longer matches the canonical owner record.")
        elif disagreeing:
            resolution = "conflict"
        else:
            resolution = "recorded"
        for assertion in disagreeing:
            conflicts.append({
                "id": f"conflict:{assessment['id']}:{selected}:{assertion.get('id')}",
                "kind": "applied_assertion_mismatch" if assertion in applied_mismatch else "owner_assertion_disagreement",
                "subject": {"type": "assessment", "id": assessment["id"]},
                "field": selected,
                "owner_value": owner_value,
                "assertion_value": assertion.get("value"),
                "assertion_id": assertion.get("id"),
                "source_kind": assertion.get("source_kind"),
                "verification": assertion.get("verification"),
                "confidence": assertion.get("confidence"),
                "evidence": _evidence_list(assertion, evidence_map),
                "why": _conflict_why(assertion, owner_value),
                "resolution": "needs_confirmation",
            })
        alternatives = [assertion_summary(assertion) for assertion in disagreeing]
        evidence_items = _evidence_list(lead, evidence_map) if lead else []
        if any(str(item.get("id")) in stale_evidence_ids for item in evidence_items):
            warnings = [*warnings, "The source changed after it was indexed; verify the current source before relying on this value."]
        return {
            "value": owner_value,
            "resolution": resolution,
            "confidence": lead.get("confidence") if lead else _owner_source(assessment)["confidence"],
            "verification": lead.get("verification") if lead else "unverified",
            "source_kind": lead.get("source_kind") if lead else "legacy_record",
            "source": _resolved_source(assessment, lead, evidence_items),
            "evidence": evidence_items,
            "alternatives": alternatives,
            "conflicts": conflicts,
            "warnings": warnings,
        }

    # No materialized owner. Resolve active assertions with the field policy.
    candidates = active
    if not candidates:
        return {
            "value": None,
            "resolution": "missing",
            "confidence": "unverified",
            "verification": "unverified",
            "source_kind": None,
            "source": None,
            "evidence": [],
            "alternatives": [],
            "conflicts": [],
            "warnings": warnings,
        }
    ranked = sorted(candidates, key=assertion_rank, reverse=True)
    top = ranked[0]
    top_rank = assertion_rank(top)
    tied = [assertion for assertion in ranked[1:] if assertion_rank(assertion) == top_rank]
    different = [assertion for assertion in tied if assertion.get("value") != top.get("value")]
    if different:
        resolution = "needs_confirmation"
        for assertion in [top, *different]:
            conflicts.append({
                "id": f"conflict:{assessment['id']}:{selected}:{assertion.get('id')}",
                "kind": "assertion_ranking_tie",
                "subject": {"type": "assessment", "id": assessment["id"]},
                "field": selected,
                "owner_value": None,
                "assertion_value": assertion.get("value"),
                "assertion_id": assertion.get("id"),
                "source_kind": assertion.get("source_kind"),
                "verification": assertion.get("verification"),
                "confidence": assertion.get("confidence"),
                "evidence": _evidence_list(assertion, evidence_map),
                "why": "Two or more current sources cannot be separated safely.",
                "resolution": "needs_confirmation",
            })
    else:
        resolution = "derived"
    evidence_items = _evidence_list(top, evidence_map)
    if any(str(item.get("id")) in stale_evidence_ids for item in evidence_items):
        warnings = [*warnings, "The source changed after it was indexed; verify the current source before relying on this value."]
    return {
        "value": top.get("value"),
        "resolution": resolution,
        "confidence": top.get("confidence"),
        "verification": top.get("verification"),
        "source_kind": top.get("source_kind"),
        "source": {
            "label": top.get("source_kind"),
            "path": (evidence_items[0].get("source_path") if evidence_items else None),
            "locator": None,
            "source_kind": top.get("source_kind"),
            "verification": top.get("verification"),
            "confidence": top.get("confidence"),
            "record_basis": None,
        },
        "evidence": evidence_items,
        "alternatives": [assertion_summary(assertion) for assertion in ranked[1:]],
        "conflicts": conflicts,
        "warnings": warnings,
    }


def _conflict_why(assertion: dict[str, Any], owner_value: Any) -> str:
    return (
        f"A {str(assertion.get('source_kind', 'source')).replace('_', ' ')} says "
        f"{assertion.get('value')!s}, while the canonical owner record says {owner_value!s}."
    )


def public_assessment(
    assessment: dict[str, Any],
    assertions: list[dict[str, Any]],
    evidence_map: dict[str, dict[str, Any]],
    links: list[dict[str, Any]],
    stale_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    fields = {"due_date": resolve_field(assessment, "due_date", assertions, evidence_map, stale_evidence_ids)}
    if assessment.get("weight") not in {None, ""}:
        fields["weight"] = {
            "value": assessment.get("weight"),
            "resolution": "recorded",
            "confidence": "likely",
            "verification": "unverified",
            "source_kind": "legacy_record",
            "source": _owner_source(assessment),
            "evidence": [],
            "alternatives": [],
            "conflicts": [],
            "warnings": [],
        }
    return {
        "id": assessment["id"],
        "course_id": assessment["course_id"],
        "semester": assessment["semester"],
        "title": assessment["title"],
        "kind": assessment["kind"],
        "status": assessment.get("status"),
        "owner": assessment.get("owner"),
        "source": assessment.get("source"),
        "fields": fields,
        "aliases": assessment.get("aliases", []),
        "external_values": assessment.get("external_values", []),
        "links": links,
        "warnings": assessment.get("warnings", []),
    }


def course_view(store: KnowledgeStore, root: Path, semester: str, course_id: str) -> dict[str, Any]:
    assessments, standalone_deadlines, warnings, context = build_assessments(store, root, semester, course_id)
    evidence_map = store.evidence_map()
    public = []
    all_conflicts: list[dict[str, Any]] = []
    for assessment in assessments:
        assertions = store.list_assertions(subject_type="assessment", subject_id=assessment["id"], field="due_date", status="active")
        links = store.list_links(assessment_id=assessment["id"])
        view = public_assessment(assessment, assertions, evidence_map, links)
        public.append(view)
        all_conflicts.extend(view["fields"]["due_date"]["conflicts"])
    schema = store.read_schema() if store.schema_path.exists() else {}
    return {
        "semester": semester,
        "course": context.get("course"),
        "assessments": public,
        "standalone_deadlines": standalone_deadlines,
        "conflicts": all_conflicts,
        "warnings": warnings + list(schema.get("migration", {}).get("warnings", [])),
        "migration": schema.get("migration", {"status": "not_run"}),
    }
