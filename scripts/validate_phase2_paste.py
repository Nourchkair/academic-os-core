"""Validate the Phase 2 paste-intake slice against a copied real workspace.

The workspace must be a copy. This script performs consequential changes inside
that copy and never touches the original academic workspace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from academia_os.assignment_history import list_assignment_history
from academia_os.intake import IntakeService
from academia_os.knowledge import KnowledgeService


COURSE = "POL2108A - Modern Political Theory I"
TITLE = "Second Essay"


def _fail(message: str) -> None:
    raise AssertionError(message)


def validate(workspace: Path, semester: str, profile: Path) -> dict[str, Any]:
    root = workspace.resolve()
    if not root.is_dir():
        raise ValueError(f"workspace not found: {root}")
    service = IntakeService(root, semester)
    text = "My professor moved the Second Essay deadline to November 20."
    pasted = service.submit_paste(text_value=text, course_id=COURSE, source_kind="professor_announcement")
    intake = pasted["intake"]
    source = root / intake["source_path"]
    if not source.is_file() or text not in source.read_text(encoding="utf-8"):
        _fail("the exact pasted text was not preserved in the course inbox")
    if len(pasted["candidates"]) != 1:
        _fail(f"expected one candidate, got {len(pasted['candidates'])}")
    candidate = pasted["candidates"][0]
    if candidate["status"] != "resolved" or candidate["value"] != "2026-11-20":
        _fail(f"candidate was not resolved correctly: {candidate}")
    if candidate["resolution"].get("assessment_title") != TITLE:
        _fail("candidate resolved to the wrong assessment")

    changeset = service.propose_candidate(candidate["id"])
    if changeset["status"] != "proposed":
        _fail(f"candidate did not produce a proposed ChangeSet: {changeset['status']}")
    if not changeset["evidence"] or changeset["evidence"][0]["source_path"] != intake["source_path"]:
        _fail("the ChangeSet did not retain the preserved source evidence")

    knowledge = KnowledgeService(root, semester)
    knowledge.approve_changeset(changeset["id"])
    executed = knowledge.execute_changeset(changeset["id"])
    if executed["status"] != "verified":
        _fail(f"the ChangeSet did not verify: {executed['status']}")
    history = list_assignment_history(root, semester, COURSE)
    if next(item for item in history if item["title"] == TITLE)["due_date"] != "2026-11-20":
        _fail("the assessment owner did not update")
    shown = service.show_candidate(candidate["id"])
    if shown["candidate"]["status"] != "proposed" or shown["changeset"]["status"] != "verified":
        _fail("the candidate did not retain its verified ChangeSet link")

    duplicate = service.submit_paste(text_value=text, course_id=COURSE, source_kind="professor_announcement")
    if duplicate["intake"]["id"] != intake["id"] or len(duplicate["candidates"]) != 1:
        _fail("a duplicate paste created a second intake or candidate")

    ambiguous = service.submit_paste(
        text_value="The professor moved the Final Essay deadline to December 5.",
        course_id=COURSE,
    )
    ambiguous_candidate = ambiguous["candidates"][0]
    if ambiguous_candidate["status"] != "needs_entity":
        _fail(f"an unmatched assessment should need a decision, got {ambiguous_candidate['status']}")
    if not ambiguous_candidate["available_assessments"]:
        _fail("the ambiguous candidate did not expose assessment choices")
    service.reject_candidate(ambiguous_candidate["id"])

    inferred = service.submit_paste(
        text_value="POL2108A update: the Second Essay deadline moved to November 21.",
    )
    inferred_candidate = inferred["candidates"][0]
    if inferred_candidate["course_id"] != COURSE:
        _fail("the course code in the paste was not inferred correctly")

    no_change = service.submit_paste(
        text_value="No academic deadlines changed today. Have a good weekend.",
        course_id=COURSE,
    )
    if no_change["intake"]["status"] != "no_candidates" or no_change["candidates"]:
        _fail("a non-deadline paste produced candidates")
    if not (root / no_change["intake"]["source_path"]).is_file():
        _fail("a non-deadline paste did not preserve its source")

    return {
        "status": "passed",
        "workspace": str(root),
        "semester": semester,
        "source_path": intake["source_path"],
        "candidate_id": candidate["id"],
        "changeset_id": changeset["id"],
        "assessment_due": next(item for item in history if item["title"] == TITLE)["due_date"],
        "candidate_status": shown["candidate"]["status"],
        "changeset_status": shown["changeset"]["status"],
        "duplicate_intake_reused": True,
        "ambiguous_candidate": ambiguous_candidate["status"],
        "inferred_course": inferred_candidate["course_id"],
        "no_candidate_source_preserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.workspace, args.semester, args.profile or Path("."))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
