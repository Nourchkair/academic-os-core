from __future__ import annotations

from pathlib import Path

from academia_os.domain import Deadline, DomainProjection, Evidence
from academia_os.library import list_material
from academia_os.workspace import build_workspace_snapshot
from tests.test_agent_neutral_core import minimal_config


def test_library_lists_current_semester_material_with_transparent_categories(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    semester = root / "Fall 2026"
    course = semester / "POL 2103 - Politics"
    files = {
        course / "01_COURSE" / "Syllabus Fall 2026.pdf": "syllabus",
        course / "05_REFERENCE" / "Required reading.pdf": "reading",
        course / "02_WEEKS" / "Week 1 notes.md": "notes",
        course / "00_INBOX" / "downloaded-material.pdf": "imported",
        semester / "00_INBOX" / "unknown-material.pdf": "imported",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (course / "01_COURSE" / "Course_Status.md").write_text("# operational status\n", encoding="utf-8")
    (semester / "SEMESTER_TASKS.md").write_text("# operational task template\n", encoding="utf-8")
    (root / ".academia").mkdir(parents=True, exist_ok=True)
    (root / ".academia" / "domain.json").write_text("{}\n", encoding="utf-8")

    items = list_material(root, "Fall 2026")

    assert {(item["name"], item["category"]) for item in items} == {
        ("Syllabus Fall 2026.pdf", "syllabi"),
        ("Required reading.pdf", "readings"),
        ("Week 1 notes.md", "notes"),
        ("downloaded-material.pdf", "imports"),
        ("unknown-material.pdf", "imports"),
    }
    assert next(item for item in items if item["name"] == "unknown-material.pdf")["course_id"] is None
    assert all(".academia" not in item["path"] for item in items)


def test_workspace_snapshot_includes_material_counts_and_structured_domain_tasks(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    source = course / "01_COURSE" / "Syllabus.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"authoritative syllabus")
    (course / "00_INBOX").mkdir(parents=True, exist_ok=True)
    (course / "00_INBOX" / "reading.pdf").write_bytes(b"reading")
    evidence = Evidence(source="Syllabus.pdf", source_path=str(source), authority="official", confidence="current-confirmed")
    DomainProjection(root / ".academia" / "domain.json").upsert(
        Deadline(
            id="deadline-1",
            course_id="POL 2103 - Politics",
            title="Policy memo",
            date="2026-10-11",
            time=None,
            type="assignment",
            evidence=evidence,
        )
    )

    snapshot = build_workspace_snapshot(config)

    assert snapshot["material_count"] == 2
    assert snapshot["inbox_count"] == 1
    assert snapshot["available_semesters"] == ["Fall 2026"]
    assert snapshot["courses"][0]["material_count"] == 2
    assert any(task["title"] == "Policy memo" and task["due_date"] == "2026-10-11" for task in snapshot["tasks"])
    assert any(task["confidence"] == "current-confirmed" for task in snapshot["tasks"] if task["title"] == "Policy memo")
