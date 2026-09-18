from pathlib import Path

from academia_os.course_identity import course_code, course_records


def test_course_code_preserves_code_without_a_title(tmp_path: Path) -> None:
    assert course_code("POL 2103 - Politics") == "POL 2103"
    assert course_code("POL 2103") == "POL 2103"


def test_course_records_use_the_full_code_for_code_only_course_names(tmp_path: Path) -> None:
    semester = tmp_path / "Fall 2026"
    course = semester / "POL 2103"
    (course / "01_COURSE").mkdir(parents=True)

    records = course_records(semester)

    assert records == [{"id": "POL 2103", "code": "POL 2103", "name": "POL 2103", "path": str(course)}]
