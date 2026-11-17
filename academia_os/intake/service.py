"""Paste intake, source preservation, candidate resolution, and ChangeSet bridge."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..activity import ActivityLog
from ..config import SEMESTER_PATTERN
from ..course_identity import course_records, resolve_course_identifier
from ..knowledge import KnowledgeService
from ..knowledge.model import AGENT_ACTOR_PREFIX, AGENT_CHANNELS, USER_ACTORS, USER_CHANNELS, normalize, now
from .model import Candidate, Intake, SOURCE_KINDS, new_id, text
from .parser import ParsedCandidate, parse_announcement
from .store import IntakeStore


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-")
    return (cleaned[:48].strip("-") or "Academic announcement")


class IntakeService:
    def __init__(self, workspace_root: Path, semester: str) -> None:
        root = Path(workspace_root).expanduser().resolve()
        if SEMESTER_PATTERN.fullmatch(semester) is None:
            raise ValueError("semester must use a term and four-digit year, such as Fall 2026")
        self.root = root
        self.semester = semester
        self.store = IntakeStore(root)
        self.knowledge = KnowledgeService(root, semester)

    def _activity(self) -> ActivityLog:
        return ActivityLog(self.root / ".academia" / "activity.jsonl")

    def _require_user(self, actor: str, channel: str) -> None:
        if actor.startswith(AGENT_ACTOR_PREFIX) or channel in AGENT_CHANNELS:
            raise PermissionError("an agent may submit intake and propose ChangeSets but may not resolve or reject a candidate")
        if actor not in USER_ACTORS or channel not in USER_CHANNELS:
            raise PermissionError("a user-authorized dashboard or CLI channel is required")

    def _course(self, course_id: str | None) -> dict[str, Any] | None:
        if not course_id:
            return None
        return resolve_course_identifier(course_records(self.root / self.semester), course_id)

    def _infer_course(self, value: str) -> tuple[dict[str, Any] | None, list[str]]:
        courses = course_records(self.root / self.semester)
        haystack = value.casefold()
        matches: dict[str, dict[str, Any]] = {}
        for course in courses:
            candidates = [course.get("id"), course.get("code"), course.get("name")]
            name = str(course.get("name") or "")
            if " - " in name:
                candidates.append(name.split(" - ", 1)[1])
            for candidate in candidates:
                cleaned = str(candidate or "").strip()
                if not cleaned:
                    continue
                pattern = r"(?<![a-z0-9])" + re.escape(cleaned.casefold()) + r"(?![a-z0-9])"
                if re.search(pattern, haystack):
                    matches[str(course["id"])] = course
                    break
        if len(matches) == 1:
            return next(iter(matches.values())), []
        if len(matches) > 1:
            return None, [f"More than one course is mentioned: {', '.join(sorted(matches))}."]
        return None, []

    def _source_note(self, value: str, course: dict[str, Any] | None, source_kind: str) -> Path:
        if course is None:
            folder = self.root / self.semester / "00_INBOX"
        else:
            folder = Path(str(course["path"])) / "00_INBOX"
        if folder.is_symlink():
            raise ValueError("the intake inbox cannot be a symbolic link")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slug = _slug(value.splitlines()[0] if value.splitlines() else value)
        base = f"Announcement - {stamp} - {slug}"
        for index in range(1, 1000):
            suffix = "" if index == 1 else f" ({index})"
            path = folder / f"{base}{suffix}.md"
            try:
                handle = path.open("x", encoding="utf-8")
            except FileExistsError:
                continue
            with handle:
                handle.write("# Academic announcement\n\n")
                handle.write(f"- Captured: {now()}\n")
                handle.write(f"- Source: {'Professor announcement' if source_kind == 'professor_announcement' else 'Student-provided announcement'}\n")
                handle.write(f"- Course context: {course['id'] if course else 'Unassigned'}\n")
                handle.write(f"- Original text SHA-256: {_sha256(value)}\n\n")
                handle.write("## Original text\n\n")
                handle.write(value)
                handle.write("\n")
            return path
        raise ValueError("could not allocate a unique intake source filename")

    def _assessment_options(self, course_id: str | None) -> list[dict[str, Any]]:
        if not course_id:
            return []
        view = self.knowledge.course_view(course_id, include_freshness=False)
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "kind": item.get("kind"),
                "due_date": item.get("fields", {}).get("due_date", {}).get("value"),
                "verification": item.get("fields", {}).get("due_date", {}).get("verification"),
            }
            for item in view.get("assessments", [])
        ]

    def _resolve_assessment(self, course_id: str | None, title: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        if not course_id or not title:
            return None, self._assessment_options(course_id), None
        options = self._assessment_options(course_id)
        matches = [item for item in options if normalize(item["title"]) == normalize(title)]
        if len(matches) == 1:
            return matches[0], options, None
        if len(matches) > 1:
            return None, options, "More than one assessment has that title."
        return None, options, "No exact assessment title match."

    def _candidate_status(
        self,
        parsed: ParsedCandidate,
        course: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        if parsed.value is None:
            return "needs_confirmation", {"why": "The announcement contains more than one possible date."}
        if course is None:
            return "needs_course", {"why": "No course could be resolved from the selected context or text."}
        if not parsed.entity_title:
            return "needs_entity", {"why": "No assessment title was recognized."}
        assessment, options, why = self._resolve_assessment(str(course["id"]), parsed.entity_title)
        if assessment is None:
            return "needs_entity", {"why": why or "The assessment could not be resolved.", "candidates": options}
        resolution = {
            "course_id": course["id"],
            "assessment_id": assessment["id"],
            "assessment_title": assessment["title"],
            "current_due_date": assessment.get("due_date"),
            "why": "exact_title_match",
        }
        if assessment.get("due_date") == parsed.value:
            return "no_change", resolution
        return "resolved", resolution

    def _intake_status(self, candidates: list[Candidate]) -> str:
        statuses = {candidate.status for candidate in candidates}
        if not candidates:
            return "no_candidates"
        if "resolved" in statuses or "proposed" in statuses or "no_change" in statuses:
            return "candidates_found"
        if statuses <= {"needs_course"}:
            return "needs_course"
        if statuses <= {"needs_entity"}:
            return "needs_entity"
        if statuses <= {"needs_confirmation"}:
            return "needs_confirmation"
        return "candidates_found"

    def _public_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        value = dict(candidate)
        course_id = value.get("course_id")
        value["available_assessments"] = self._assessment_options(course_id)
        return value

    def submit_paste(
        self,
        *,
        text_value: str,
        course_id: str | None = None,
        source_kind: str = "student_report",
        actor: str = "user",
        force: bool = False,
    ) -> dict[str, Any]:
        value = text(text_value, "announcement text", required=True, maximum=20000)
        if source_kind not in SOURCE_KINDS:
            raise ValueError("source kind must be student_report or professor_announcement")
        course = self._course(course_id)
        warnings: list[str] = []
        if course is None:
            inferred, inference_warnings = self._infer_course(value)
            course = inferred
            warnings.extend(inference_warnings)
        dedupe = _sha256(f"{course['id'] if course else ''}\n{value}")
        if not force:
            existing = self.store.find_by_dedupe_key(dedupe)
            if existing is not None:
                candidates = [
                    self._public_candidate(self.store.get_candidate(candidate_id))
                    for candidate_id in existing.get("candidate_ids", [])
                ]
                return {
                    "intake": existing,
                    "candidates": candidates,
                    "available_assessments": self._assessment_options(existing.get("course_id")),
                    "warnings": ["This exact announcement was already captured; the existing intake was returned."],
                }
        source_path = self._source_note(value, course, source_kind)
        relative_path = source_path.relative_to(self.root).as_posix()
        parsed_candidates, parse_warnings = parse_announcement(value, self.semester)
        warnings.extend(parse_warnings)
        intake_id = new_id("intake")
        candidates: list[Candidate] = []
        for parsed in parsed_candidates:
            status, resolution = self._candidate_status(parsed, course)
            candidate_warnings = list(parsed.warnings)
            if status == "no_change":
                candidate_warnings.append("The proposed date already matches the current recorded deadline.")
            candidates.append(Candidate(
                id=new_id("candidate"),
                intake_id=intake_id,
                semester=self.semester,
                course_id=str(course["id"]) if course else None,
                entity_type="assessment",
                entity_title=parsed.entity_title,
                field="due_date",
                value=parsed.value,
                value_type="date",
                source_path=relative_path,
                source_locator="pasted text",
                source_excerpt=parsed.excerpt,
                source_kind=source_kind,
                confidence=parsed.confidence,
                specificity=parsed.specificity,
                status=status,
                resolution=resolution,
                warnings=candidate_warnings,
                created_by=actor,
            ))
        intake = Intake(
            id=intake_id,
            semester=self.semester,
            course_id=str(course["id"]) if course else None,
            source_kind=source_kind,
            text_sha256=_sha256(value),
            source_path=relative_path,
            text=value,
            status=self._intake_status(candidates),
            candidate_ids=[candidate.id for candidate in candidates],
            warnings=warnings,
            created_by=actor,
            dedupe_key=dedupe,
        )
        self.store.create_intake(intake)
        if candidates:
            self.store.add_candidates(candidates)
        self._activity().append(
            event_type="intake.source.preserved",
            title="Academic announcement captured",
            course=str(course["id"]) if course else None,
            source=relative_path,
            confidence="user-confirmed",
            actor=actor,
            details={"intake_id": intake.id, "candidates": len(candidates), "source_kind": source_kind},
        )
        return {
            "intake": intake.to_dict(),
            "candidates": [self._public_candidate(candidate.to_dict()) for candidate in candidates],
            "available_assessments": self._assessment_options(str(course["id"]) if course else None),
            "warnings": warnings,
        }

    def list_candidates(self, *, course_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        values = self.store.list_candidates(semester=self.semester, course_id=course_id, status=status)
        return {
            "semester": self.semester,
            "candidates": [self._public_candidate(item) for item in values],
        }

    def show_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.store.get_candidate(candidate_id)
        result = {
            "candidate": self._public_candidate(candidate),
            "intake": self.store.get_intake(str(candidate["intake_id"])),
            "changeset": None,
        }
        if candidate.get("proposed_change_id"):
            result["changeset"] = self.knowledge.get_changeset(str(candidate["proposed_change_id"]))
        return result

    def resolve_candidate(
        self,
        candidate_id: str,
        *,
        course_id: str | None = None,
        assessment_id: str | None = None,
        actor: str = "user",
        channel: str = "cli_user",
    ) -> dict[str, Any]:
        self._require_user(actor, channel)
        candidate = self.store.get_candidate(candidate_id)
        if course_id is None and assessment_id is None:
            raise ValueError("provide a course or an assessment")
        if assessment_id:
            assessment_view = self.knowledge.assessment_view(assessment_id, course_id, include_freshness=False)
            assessment = assessment_view["assessment"]
            resolved_course = str(assessment["course_id"])
            resolution = {
                "course_id": resolved_course,
                "assessment_id": assessment["id"],
                "assessment_title": assessment["title"],
                "current_due_date": assessment.get("fields", {}).get("due_date", {}).get("value"),
                "why": "student_selected_assessment",
            }
        else:
            resolved_course = str(self._course(course_id)["id"])
            assessment, _options, why = self._resolve_assessment(resolved_course, candidate.get("entity_title"))
            if assessment is None:
                raise ValueError(why or "the assessment could not be resolved")
            resolution = {
                "course_id": resolved_course,
                "assessment_id": assessment["id"],
                "assessment_title": assessment["title"],
                "current_due_date": assessment.get("due_date"),
                "why": "student_selected_course_and_exact_title",
            }
        status = "no_change" if resolution.get("current_due_date") == candidate.get("value") else "resolved"

        def transition(item: dict[str, Any]) -> dict[str, Any]:
            item["course_id"] = resolution["course_id"]
            item["resolution"] = resolution
            item["status"] = status
            return item

        updated = self.store.update_candidate(candidate_id, transition)
        self._activity().append(
            event_type="intake.candidate.resolved",
            title=f"Intake candidate resolved: {resolution.get('assessment_title')}",
            course=resolution["course_id"],
            source=str(candidate.get("source_path")),
            confidence="user-confirmed",
            actor=actor,
            details={"candidate_id": candidate_id, "assessment_id": resolution["assessment_id"], "status": status},
        )
        return {"candidate": self._public_candidate(updated), "available_assessments": self._assessment_options(resolution["course_id"])}

    def propose_candidate(
        self,
        candidate_id: str,
        *,
        actor: str = "user",
        channel: str = "cli_user",
    ) -> dict[str, Any]:
        candidate = self.store.get_candidate(candidate_id)
        if candidate.get("proposed_change_id"):
            try:
                existing_changeset = self.knowledge.get_changeset(str(candidate["proposed_change_id"]))
            except KeyError:
                existing_changeset = None
            if existing_changeset is not None and existing_changeset.get("status") not in {"cancelled", "superseded"}:
                return existing_changeset
            self.store.update_candidate(
                candidate_id,
                lambda item: {**item, "status": "resolved", "proposed_change_id": None},
            )
            candidate = self.store.get_candidate(candidate_id)
        if candidate.get("status") not in {"resolved"}:
            raise ValueError(f"candidate is not ready for a ChangeSet: {candidate.get('status')}")
        resolution = candidate.get("resolution") if isinstance(candidate.get("resolution"), dict) else {}
        course_id = resolution.get("course_id") or candidate.get("course_id")
        assessment_id = resolution.get("assessment_id")
        if not course_id or not assessment_id or not candidate.get("value"):
            raise ValueError("candidate is missing a resolved course, assessment, or date")
        changeset = self.knowledge.propose_deadline_change(
            course_id=str(course_id),
            assessment_id=str(assessment_id),
            new_date=str(candidate["value"]),
            source_kind=str(candidate.get("source_kind") or "student_report"),
            source_label="Pasted academic announcement",
            evidence_path=str(candidate.get("source_path")),
            evidence_locator=str(candidate.get("source_locator") or "pasted text"),
            evidence_excerpt=str(candidate.get("source_excerpt") or ""),
            note="Created from academic intake.",
            actor=actor,
            channel=channel,
        )

        def transition(item: dict[str, Any]) -> dict[str, Any]:
            item["status"] = "proposed"
            item["proposed_change_id"] = changeset["id"]
            return item

        self.store.update_candidate(candidate_id, transition)
        self.store.update_intake(str(candidate["intake_id"]), lambda item: {**item, "status": "proposed"})
        self._activity().append(
            event_type="intake.candidate.proposed",
            title=f"ChangeSet proposed from intake: {changeset.get('title')}",
            course=str(course_id),
            source=str(candidate.get("source_path")),
            confidence="unverified",
            actor=actor,
            details={"candidate_id": candidate_id, "changeset_id": changeset["id"]},
        )
        return changeset

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        actor: str = "user",
        channel: str = "cli_user",
    ) -> dict[str, Any]:
        self._require_user(actor, channel)
        candidate = self.store.get_candidate(candidate_id)
        if candidate.get("status") == "proposed":
            raise ValueError("a candidate with a proposed ChangeSet must be cancelled through the ChangeSet")
        updated = self.store.update_candidate(candidate_id, lambda item: {**item, "status": "rejected"})
        self._activity().append(
            event_type="intake.candidate.rejected",
            title="Academic intake candidate rejected",
            course=str(candidate.get("course_id") or ""),
            source=str(candidate.get("source_path")),
            confidence="user-confirmed",
            actor=actor,
            details={"candidate_id": candidate_id},
        )
        return {"candidate": self._public_candidate(updated)}
