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


def test_import_command_copies_source_and_stages_processing_record(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
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
        "--name", "Nour Student", "--institution", "Example University", "--program", "History",
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


def test_workspace_create_is_previewed_then_uses_existing_installer(tmp_path: Path) -> None:
    root = tmp_path / "Fresh University"
    profile = tmp_path / ".academic-os" / "profile.json"
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    common = [
        sys.executable, "-m", "academia_os", "--profile", str(profile), "workspace", "create", str(root),
        "--name", "Nour Student", "--institution", "Example University", "--program", "History",
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
            "--name", "Nour Student", "--institution", "Example University", "--program", "History",
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
