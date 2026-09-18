from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_agent_neutral_core import minimal_config
from tests.test_attachment import _populated_workspace
from academia_os.config import save_config
from academia_os.review import ReviewQueue
from academia_os.activity import ActivityLog
from installer.migration import build_migration_plan, write_migration_plan

ROOT = Path(__file__).resolve().parents[1]


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True, exist_ok=True)
    (course / "00_INBOX").mkdir(exist_ok=True)
    (course / "00_INBOX" / "announcement.pdf").write_bytes(b"announcement")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), *args], cwd=ROOT, env=env, text=True, capture_output=True)


def test_status_and_courses_json_are_machine_readable(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "status", "--json")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["student"]["name"] == "Alex Student"
    assert status["workspace"]["semester"] == "Fall 2026"
    courses = run_cli(tmp_path, "courses", "--json")
    assert courses.returncode == 0, courses.stderr
    assert json.loads(courses.stdout)[0]["code"] == "POL 2103"


def test_library_command_lists_material_in_the_active_semester(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "library", "--json")
    assert result.returncode == 0, result.stderr
    items = json.loads(result.stdout)
    assert any(item["name"] == "announcement.pdf" and item["category"] == "imports" for item in items)


def test_inbox_command_detects_preexisting_inbox_files(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "inbox", "--json")
    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert len(records) == 1
    assert records[0]["status"] == "PENDING"
    assert records[0]["source_path"].endswith("announcement.pdf")


def test_review_and_activity_commands_read_persisted_state(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    state_root = Path(config["academic"]["root_directory"]) / ".academia"
    item = ReviewQueue(state_root / "review.json").add(kind="source_verification", title="Verify reading", course="ECO 2142")
    ActivityLog(state_root / "activity.jsonl").append(event_type="reading.imported", title="Reading imported", course="ECO 2142", source="Week 4 Reading.pdf", confidence="PROBABLE MATCH — VERIFY MANUALLY")
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    review = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert review.returncode == 0
    assert json.loads(review.stdout)[0]["id"] == item.id
    activity = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "activity", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert activity.returncode == 0
    assert json.loads(activity.stdout)[0]["event_type"] == "reading.imported"


def test_settings_preview_does_not_write_until_apply(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    preview = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "settings", "update", "--set", "student.name=Updated", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["applied"] is False
    assert json.loads(profile.read_text(encoding="utf-8"))["student"]["name"] == "Alex Student"
    applied = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "settings", "update", "--set", "student.name=Updated", "--apply", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(profile.read_text(encoding="utf-8"))["student"]["name"] == "Updated"


def test_review_decide_command_records_specific_choice(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    item = ReviewQueue(root / ".academia" / "review.json").add(
        kind="deadline_conflict",
        title="Assignment 2 deadline",
        course="HIS 101 - History",
        details={"current": "October 8", "new": "October 11"},
    )
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "decide", item.id, "use_new", "--json"],
        cwd=ROOT, env=env, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["status"] == "approved"
    assert value["details"]["decision"] == "use_new"


def test_import_command_copies_source_and_stages_processing_record(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    (root / "Fall 2026" / "POL 2103 - Politics" / "01_COURSE").mkdir(parents=True)
    destination = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX"
    source = tmp_path / "downloaded-reading.pdf"
    source.write_bytes(b"reading")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "import", str(source), "--destination", str(destination), "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    copied = Path(value["destination"])
    assert copied.is_file()
    assert copied.read_bytes() == b"reading"
    assert source.is_file()
    assert value["state_path"] == str(root / ".academia" / "processing.json")
    assert len(json.loads((root / ".academia" / "processing.json").read_text(encoding="utf-8"))) == 1


def test_import_source_label_preserves_browser_provenance_in_metadata_review_and_activity(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    (root / "Fall 2026").mkdir(parents=True)
    destination = root / "Fall 2026" / "00_INBOX"
    source = tmp_path / "temporary-upload-name.pdf"
    source.write_bytes(b"browser bytes")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    label = "browser-upload:week-4.pdf"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "academia_os",
            "--profile",
            str(profile),
            "import",
            str(source),
            "--destination",
            str(destination),
            "--source-label",
            label,
            "--uncertain",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["source_type"] == "browser_upload"
    assert value["source_label"] == label
    assert value["original_file"] == label
    assert str(source) not in result.stdout
    activity = json.loads((root / ".academia" / "activity.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert activity["source"] == label
    review = json.loads((root / ".academia" / "review.json").read_text(encoding="utf-8"))[0]
    assert review["details"]["original_file"] == label
    assert review["details"]["source_type"] == "browser_upload"


def test_workspace_inspect_is_available_without_a_profile_and_is_read_only(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    discover = subprocess.run([sys.executable, "-m", "academia_os", "workspace", "discover", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert discover.returncode == 0, discover.stderr
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "workspace", "inspect", str(root), "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["recognized"] is True
    assert value["course_count"] == 2
    assert not (root / ".academia").exists()
    assert {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_workspace_attach_requires_apply_and_writes_only_profile_after_confirmation(tmp_path: Path) -> None:
    root = _populated_workspace(tmp_path)
    profile = tmp_path / ".academic-os" / "profile.json"
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    common = [
        sys.executable, "-m", "academia_os", "--profile", str(profile), "workspace", "attach", str(root),
        "--name", "Alex Student", "--institution", "Example University", "--program", "History",
        "--timezone", "America/Toronto", "--semester", "Fall 2026",
    ]
    preview = subprocess.run(common + ["--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["applied"] is False
    assert not profile.exists()
    assert not (root / ".academia").exists()

    applied = subprocess.run(common + ["--apply", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(profile.read_text(encoding="utf-8"))["academic"]["root_directory"] == str(root)
    assert not (root / ".academia").exists()


def test_uncertain_import_creates_review_item_without_moving_original(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    (root / "Fall 2026").mkdir(parents=True)
    destination = root / "Fall 2026" / "00_INBOX"
    source = tmp_path / "unknown-reading.pdf"
    source.write_bytes(b"reading")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [
            sys.executable, "-m", "academia_os", "--profile", str(profile), "import", str(source),
            "--destination", str(destination), "--uncertain", "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert source.is_file()
    reviews = json.loads((root / ".academia" / "review.json").read_text(encoding="utf-8"))
    assert reviews[0]["kind"] == "import_classification"
    assert reviews[0]["status"] == "open"


def test_import_rejects_workspace_root_and_non_inbox_destinations(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    source = tmp_path / "reading.pdf"
    source.write_bytes(b"reading")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    for destination in (root, root / "LooseDump", root / ".academia" / "inbox"):
        result = subprocess.run(
            [sys.executable, "-m", "academia_os", "--profile", str(profile), "import", str(source), "--destination", str(destination), "--json"],
            cwd=ROOT, env=env, text=True, capture_output=True,
        )
        assert result.returncode == 2
        assert "workspace inbox" in result.stdout
    assert source.is_file()


def test_import_rejects_operational_state_as_a_source(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    (root / "Fall 2026").mkdir(parents=True)
    source = root / ".academia" / "processing.json"
    source.parent.mkdir(parents=True)
    source.write_text("[]", encoding="utf-8")
    destination = root / "Fall 2026" / "00_INBOX"
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "import", str(source), "--destination", str(destination), "--json"],
        cwd=ROOT, env=env, text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert "operational state" in result.stdout


def test_workspace_create_is_previewed_then_uses_existing_installer(tmp_path: Path) -> None:
    root = tmp_path / "Fresh University"
    profile = tmp_path / ".academic-os" / "profile.json"
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    common = [
        sys.executable, "-m", "academia_os", "--profile", str(profile), "workspace", "create", str(root),
        "--name", "Alex Student", "--institution", "Example University", "--program", "History",
        "--timezone", "America/Toronto", "--semester", "Fall 2026",
    ]
    preview = subprocess.run(common + ["--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["applied"] is False
    assert not root.exists()

    applied = subprocess.run(common + ["--apply", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert applied.returncode == 0, applied.stderr
    assert (root / "ACADEMIC_OS_RULES.md").is_file()
    assert (root / "COURSE_TEMPLATE").is_dir()
    assert json.loads(profile.read_text(encoding="utf-8"))["academic"]["root_directory"] == str(root)


def test_workspace_create_preserves_stale_profile_before_initializing(tmp_path: Path) -> None:
    root = tmp_path / "Fresh University"
    profile = tmp_path / ".academic-os" / "profile.json"
    profile.parent.mkdir()
    profile.write_text(json.dumps({"student": {"name": "Alex Student"}, "academic": {"root_directory": str(tmp_path / "pytest-of-old")}}), encoding="utf-8")
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [
            sys.executable, "-m", "academia_os", "--profile", str(profile), "workspace", "create", str(root),
            "--name", "Alex Student", "--institution", "Example University", "--program", "History",
            "--timezone", "America/Toronto", "--semester", "Fall 2026", "--apply", "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["profile_state"] == "stale_test_data"
    assert "Alex Student" in Path(value["backup_profile"]).read_text(encoding="utf-8")
    assert json.loads(profile.read_text(encoding="utf-8"))["academic"]["root_directory"] == str(root)


def test_extract_syllabus_previews_without_mutating_and_apply_records_domain_activity(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    syllabus = tmp_path / "POL2103_Syllabus.md"
    syllabus.write_text(
        """# POL 2103 - Politics
Course: POL 2103 - Politics
## Assessments
- Research Essay — 25% — Due October 19, 2026
""",
        encoding="utf-8",
    )
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    command = [sys.executable, "-m", "academia_os", "--profile", str(profile), "extract", "syllabus", str(syllabus), "--course", "POL 2103 - Politics", "--verified-current", "--json"]

    preview = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    assert preview.returncode == 0, preview.stderr
    preview_value = json.loads(preview.stdout)
    assert preview_value["applied"] is False
    assert preview_value["reconciliation"]["applied"] is False
    assert not (root / ".academia").exists()

    applied = subprocess.run(command + ["--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert applied.returncode == 0, applied.stderr
    applied_value = json.loads(applied.stdout)
    assert applied_value["applied"] is True
    assert (root / ".academia" / "domain.json").is_file()
    activity = json.loads((root / ".academia" / "activity.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert activity["event_type"] == "syllabus.reconciled"


def test_cli_deadline_conflict_requires_review_decision_then_executes_domain_change(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    course = root / "Fall 2026" / "POL 2103 - Politics"
    (course / "01_COURSE").mkdir(parents=True)
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("Course: POL 2103 - Politics\n## Assessments\n- Research Essay — 25% — Due October 19, 2026\n", encoding="utf-8")
    second.write_text("Course: POL 2103 - Politics\n## Assessments\n- Research Essay — 25% — Due October 22, 2026\n", encoding="utf-8")
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    base = [sys.executable, "-m", "academia_os", "--profile", str(profile), "extract", "syllabus"]

    for source in (first,):
        result = subprocess.run(base + [str(source), "--course", "POL 2103 - Politics", "--verified-current", "--apply", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    conflict = subprocess.run(base + [str(second), "--course", "POL 2103 - Politics", "--verified-current", "--apply", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert conflict.returncode == 0, conflict.stderr
    conflict_value = json.loads(conflict.stdout)
    review_id = conflict_value["reconciliation"]["reviews"][0]["id"]

    decide = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "decide", review_id, "use_new", "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert decide.returncode == 0, decide.stderr
    execute = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "review", "execute", review_id, "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert execute.returncode == 0, execute.stderr
    domain = json.loads((root / ".academia" / "domain.json").read_text(encoding="utf-8"))
    assignment = domain["entities"]["assignment"][0]
    assert assignment["deadline"] == "2026-10-22"
    assert "October 19, 2026" in first.read_text(encoding="utf-8")


def test_migration_plan_command_writes_plan_and_review_under_runtime_directory(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    (source / "Fall 2025" / "HIS 101").mkdir(parents=True)
    (source / "Fall 2025" / "HIS 101" / "essay.pdf").write_bytes(b"essay")

    result = run_cli(tmp_path, "migration", "plan", str(source), "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["action"] == "plan"
    assert value["status"] == "planned"
    assert value["item_count"] == 1
    assert Path(value["plan_path"]).is_file()
    assert Path(value["review_path"]).is_file()
    assert value["plan_path"] == str(tmp_path / ".academic-os" / "migration" / "migration-plan.json")


def test_migration_plan_rejects_custom_runtime_directory_as_source(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    runtime_root = tmp_path / "private-cache"
    config["runtime"]["install_directory"] = str(runtime_root)
    profile = runtime_root / "profile.json"
    save_config(profile, config)
    (runtime_root / "migration").mkdir()
    (runtime_root / "migration" / "old-plan.json").write_text("runtime state", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), "migration", "plan", str(runtime_root), "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "configured runtime directory" in result.stdout
    assert not (runtime_root / "migration" / "migration-plan.json").exists()
    assert (runtime_root / "migration" / "old-plan.json").read_text(encoding="utf-8") == "runtime state"


def test_migration_status_is_read_only_and_returns_existing_report(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_value = json.loads(planned.stdout)
    plan_path = Path(plan_value["plan_path"])
    root = Path(minimal_config(tmp_path)["academic"]["root_directory"])
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    report = {"mode": "copy", "selected": 0, "copied": 0, "failed": 0}
    report_path = plan_path.parent / "migration-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = run_cli(tmp_path, "migration", "status", "--plan", str(plan_path), "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["action"] == "status"
    assert value["report"] == report
    assert {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_migration_status_rejects_symlinked_report_without_reading_target(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])
    report_path = plan_path.parent / "migration-report.json"
    protected = tmp_path / "protected-report.json"
    protected.write_text('{"status": "protected"}\n', encoding="utf-8")
    report_path.symlink_to(protected)

    result = run_cli(tmp_path, "migration", "status", "--plan", str(plan_path), "--json")

    assert result.returncode == 2
    assert "symlink" in result.stdout
    assert report_path.is_symlink()
    assert protected.read_text(encoding="utf-8") == '{"status": "protected"}\n'


def test_migration_status_rejects_symlinked_plan_even_when_target_is_inside_runtime(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])
    real_plan = plan_path.with_name("real-migration-plan.json")
    plan_path.replace(real_plan)
    plan_path.symlink_to(real_plan)

    result = run_cli(tmp_path, "migration", "status", "--plan", str(plan_path), "--json")

    assert result.returncode == 2
    assert "symlink" in result.stdout
    assert plan_path.is_symlink()
    assert real_plan.is_file()


def test_migration_execute_selects_items_collision_safely_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    first = source / "first.txt"
    second = source / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_value = json.loads(planned.stdout)
    plan_path = Path(plan_value["plan_path"])
    destination = Path(plan_value["items"][0]["destination"])
    destination.parent.mkdir(parents=True)
    destination.write_text("existing", encoding="utf-8")

    result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--item", "0", "--mode", "copy", "--apply", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["copied"] == 1
    assert value["selected"] == 1
    assert first.is_file() and first.read_text(encoding="utf-8") == "first"
    assert second.is_file()
    assert destination.read_text(encoding="utf-8") == "existing"
    collision = Path(value["destinations"][0])
    assert collision != destination
    assert collision.read_text(encoding="utf-8") == "first"
    assert (plan_path.parent / "migration-report.json").is_file()


def test_migration_execute_reports_changed_and_missing_sources(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    changed = source / "changed.txt"
    missing = source / "missing.txt"
    changed.write_text("before", encoding="utf-8")
    missing.write_text("to disappear", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])
    changed.write_text("after", encoding="utf-8")
    missing.unlink()

    result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--mode", "copy", "--apply", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["failed"] == 2
    assert value["copied"] == 0
    assert all("source" in failure for failure in value["failures"])


def test_migration_execute_requires_explicit_move_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])

    for extra in (("--mode", "move"), ("--mode", "move", "--apply")):
        result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), *extra, "--json")
        assert result.returncode == 2
        assert "confirm-move" in result.stdout
        assert document.is_file()

    applied = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--mode", "move", "--apply", "--confirm-move", "--json")
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["moved"] == 1
    assert not document.exists()


def test_migration_rejects_plan_for_another_active_workspace(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    source = tmp_path / "Legacy University"
    source.mkdir()
    (source / "notes.txt").write_text("notes", encoding="utf-8")
    foreign_root = tmp_path / "Foreign University"
    plan = build_migration_plan(source, foreign_root, "Fall 2026")
    plan_path = write_migration_plan(plan, Path(config["runtime"]["install_directory"]) / "migration")["json"]
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "migration", "status", "--plan", str(plan_path), "--json"], cwd=ROOT, env=env, text=True, capture_output=True)

    assert result.returncode == 2
    assert "active profile workspace" in result.stdout


def test_migration_rejects_plan_outside_active_runtime_directory_before_reading_or_writing(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    outside_directory = tmp_path / "outside-migration"
    outside_directory.mkdir()
    outside_plan = outside_directory / "migration-plan.json"
    outside_plan.write_text("not a migration plan", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    for command in ("status", "execute"):
        extra = ["--plan", str(outside_plan)]
        if command == "execute":
            extra.extend(["--apply", "--mode", "copy"])
        result = subprocess.run(
            [sys.executable, "-m", "academia_os", "--profile", str(profile), "migration", command, *extra, "--json"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 2
        assert "active runtime migration directory" in result.stdout
        assert outside_plan.read_text(encoding="utf-8") == "not a migration plan"
        assert not (outside_directory / "migration-report.json").exists()


def test_migration_execute_rejects_symlinked_report_without_migrating_or_overwriting_target(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_value = json.loads(planned.stdout)
    plan_path = Path(plan_value["plan_path"])
    destination = Path(plan_value["items"][0]["destination"])
    report_path = plan_path.parent / "migration-report.json"
    report_path.symlink_to(document)

    result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--mode", "copy", "--apply", "--json")

    assert result.returncode == 2
    assert "symlink" in result.stdout
    assert report_path.is_symlink()
    assert document.read_text(encoding="utf-8") == "notes"
    assert not destination.exists()


def test_migration_rejects_malformed_plan_and_operational_source(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    malformed_path = Path(config["runtime"]["install_directory"]) / "migration" / "malformed-plan.json"
    malformed_path.parent.mkdir(parents=True)
    malformed_path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    operational = Path(config["academic"]["root_directory"]) / ".academia"
    operational.mkdir(parents=True)
    (operational / "processing.json").write_text("[]", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    malformed = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "migration", "status", "--plan", str(malformed_path), "--json"], cwd=ROOT, env=env, text=True, capture_output=True)
    operational_result = subprocess.run([sys.executable, "-m", "academia_os", "--profile", str(profile), "migration", "plan", str(operational), "--json"], cwd=ROOT, env=env, text=True, capture_output=True)

    assert malformed.returncode == 2
    assert "version" in malformed.stdout
    assert operational_result.returncode == 2
    assert "operational" in operational_result.stdout


def test_migration_execute_without_apply_is_read_only_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])

    result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--item", "0", "--mode", "copy", "--json")

    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["applied"] is False
    assert value["status"] == "confirmation_required"
    assert document.is_file()
    assert not (plan_path.parent / "migration-report.json").exists()


def test_migration_execute_rejects_invalid_item_indexes(tmp_path: Path) -> None:
    source = tmp_path / "Legacy University"
    source.mkdir()
    document = source / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    planned = run_cli(tmp_path, "migration", "plan", str(source), "--json")
    assert planned.returncode == 0, planned.stderr
    plan_path = Path(json.loads(planned.stdout)["plan_path"])

    result = run_cli(tmp_path, "migration", "execute", "--plan", str(plan_path), "--item", "1", "--mode", "copy", "--apply", "--json")

    assert result.returncode == 2
    assert "out of range" in result.stdout
    assert document.is_file()
    assert not (plan_path.parent / "migration-report.json").exists()
