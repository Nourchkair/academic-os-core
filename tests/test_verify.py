from __future__ import annotations

import json
from pathlib import Path

from academia_os.config import save_config
from installer.verify import safe_to_share_audit, verify_installation
from installer.core import initialize_installation
from tests.test_agent_neutral_core import minimal_config


def test_system_health_does_not_treat_private_email_or_path_as_failure(tmp_path: Path) -> None:
    config = minimal_config(tmp_path)
    root = Path(config["academic"]["root_directory"])
    runtime = Path(config["runtime"]["install_directory"])
    initialize_installation(config, template_root=Path(__file__).resolve().parents[1] / "templates" / "University", repo_root=Path(__file__).resolve().parents[1])
    (root / "README.md").write_text((root / "README.md").read_text(encoding="utf-8") + "\nPrivate contact student@example.edu at /Users/student/Documents/University\n", encoding="utf-8")
    result = verify_installation(runtime / "profile.json")
    assert result["status"] == "pass", result


def test_safe_to_share_audit_reports_private_content_separately(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    folder.mkdir()
    (folder / "notes.md").write_text("student@example.edu\n/Users/student/Documents/University\n", encoding="utf-8")
    result = safe_to_share_audit(folder)
    assert result["status"] == "review"
    assert any("email" in finding["kind"] for finding in result["findings"])
    assert any("path" in finding["kind"] for finding in result["findings"])
