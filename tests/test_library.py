from __future__ import annotations

from pathlib import Path

from academia_os.acquisition import import_file
from academia_os.domain import Deadline, DomainProjection, Evidence
from academia_os.library import filter_material, list_material
from academia_os.processing import ProcessingStore
from academia_os.workspace import build_workspace_snapshot
from tests.test_agent_neutral_core import minimal_config


def test_library_lists_current_semester_material_with_transparent_categories(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    semester = root / "Fall 2026"
    course = semester / "POL 2103 - Politics"
    files = {
        course / "01_COURSE" / "Syllabus Fall 2026.pdf": "syllabus",
        course / "01_COURSE" / "LSR 1100-COURSE OUTLINE. FALL 2026.docx": "outline",
        course / "05_REFERENCE" / "Required reading.pdf": "reading",
        course / "02_WEEKS" / "Week 1 notes.md": "notes",
        course / "00_INBOX" / "Required reading.pdf": "imported reading",
        course / "00_INBOX" / "Chapter 3 Leisure.md": "chapter reading",
        course / "06_KNOWLEDGE" / "Source_Verification" / "Chapter 3 Leisure - Verification.md": "verification note",
        course / "00_INBOX" / "Course Outline - Updated.docx": "imported outline",
        course / "00_INBOX" / "Lecture 2.pptx": "imported lecture",
        course / "00_INBOX" / "downloaded-material.pdf": "imported",
        semester / "00_INBOX" / "unknown-material.pdf": "imported",
        course / "_TEMPLATES" / "Week_Summary.md": "template",
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
        ("LSR 1100-COURSE OUTLINE. FALL 2026.docx", "syllabi"),
        ("Required reading.pdf", "readings"),
        ("Chapter 3 Leisure.md", "readings"),
        ("Chapter 3 Leisure - Verification.md", "notes"),
        ("Required reading.pdf", "readings"),
        ("Course Outline - Updated.docx", "syllabi"),
        ("Week 1 notes.md", "notes"),
        ("Lecture 2.pptx", "notes"),
        ("downloaded-material.pdf", "other"),
        ("unknown-material.pdf", "other"),
    }
    assert not any(item["name"] == "Week_Summary.md" for item in items)
    assert next(item for item in items if item["name"] == "Syllabus Fall 2026.pdf")["intake_status"] == "organized"
    assert next(item for item in items if item["name"] == "Week 1 notes.md")["intake_status"] == "organized"
    assert next(item for item in items if item["name"] == "Required reading.pdf" and item["intake_status"] == "inbox")["category"] == "readings"
    intake_items = filter_material(items, category="imports")
    assert {item["name"] for item in intake_items} == {"Required reading.pdf", "Chapter 3 Leisure.md", "Course Outline - Updated.docx", "Lecture 2.pptx", "downloaded-material.pdf", "unknown-material.pdf"}
    assert {item["category"] for item in intake_items} == {"readings", "syllabi", "notes", "other"}
    assert next(item for item in items if item["name"] == "unknown-material.pdf")["course_id"] is None
    assert next(item for item in items if item["name"] == "unknown-material.pdf")["provenance"] is None
    assert next(item for item in items if item["name"] == "unknown-material.pdf")["intake_status"] == "inbox"
    assert all(".academia" not in item["path"] for item in items)


def test_library_labels_only_recorded_imports_as_external(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    destination = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    (destination.parent / "01_COURSE").mkdir(parents=True)
    source = tmp_path / "external.pdf"
    source.write_bytes(b"external")
    metadata = import_file(source, destination, ProcessingStore(root / ".academia" / "processing.json"), workspace_root=root)

    item = next(item for item in list_material(root, "Fall 2026") if item["name"] == "external.pdf")
    assert metadata["provenance"] == "EXTERNAL"
    assert item["provenance"] == "EXTERNAL"
    assert item["source_type"] == "manual_file"


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


def test_assignment_deadline_is_one_task_with_time_weight_and_completion(tmp_path: Path) -> None:
    from academia_os.domain import Assignment
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    evidence = Evidence(source="Syllabus.pdf", source_path=str(course / "01_COURSE/Syllabus.pdf"), source_location="page 4", authority="syllabus", confidence="likely")
    domain = DomainProjection(root / ".academia/domain.json")
    domain.upsert(Assignment("essay", course.name, "First Essay", "2026-10-08", "25%", None, None, None, "submitted", evidence))
    domain.upsert(Deadline("essay-date", course.name, "First Essay", "2026-10-08", "14:30", "assignment", evidence))
    tasks = build_workspace_snapshot(config)["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["completed"] is True
    assert tasks[0]["due_date"] == "2026-10-08"
    assert tasks[0]["due_time"] == "14:30"
    assert tasks[0]["weight"] == "25%"
    assert tasks[0]["source_location"] == "page 4"
