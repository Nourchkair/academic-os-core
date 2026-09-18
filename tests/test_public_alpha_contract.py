from __future__ import annotations

import json
from pathlib import Path

from academia_os.acquisition import capability_report
from academia_os.recommendations import get_playbook
from academia_os.workflow_preferences import WorkflowPreferencesStore

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_manifest_and_installer_sources_use_playbooks_not_legacy_integrations() -> None:
    example = json.loads((ROOT / "config" / "manifest.example.json").read_text(encoding="utf-8"))
    bootstrap = (ROOT / "installer" / "bootstrap.py").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")

    assert example["schema_version"] == 3
    assert "integrations" not in example
    assert "automation" not in example
    assert "school_portal" not in example["academic"]
    assert '"integrations"' not in bootstrap
    assert '"automation"' not in bootstrap
    assert "Optional connections" not in desktop
    assert "Prepare the daily brief" not in desktop
    assert "Agent Setup Playbooks" in desktop
    assert "authorized external agent" in desktop


def test_legacy_student_surfaces_do_not_claim_direct_external_ownership() -> None:
    surfaces = [
        ROOT / "desktop" / "README.md",
        ROOT / "templates" / "University" / "README.md",
        ROOT / "templates" / "University" / "INTEGRATION_STATUS.md",
        ROOT / "docs" / "recipient-setup-intake.md",
        ROOT / "docs" / "local-installation-handoff.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)
    assert "Optional connections" not in combined
    assert "Enable Gmail workflow" not in combined
    assert "Enable Google Calendar workflow" not in combined
    assert "generated local job" not in combined
    assert "external agent" in combined
    assert "workflow-preference" in combined


def test_daily_brief_effective_preferences_come_from_playbook_layer(tmp_path: Path) -> None:
    playbook = get_playbook("daily_academic_brief")
    shown = WorkflowPreferencesStore(tmp_path).show("daily_academic_brief")
    assert shown["effective_preferences"] == playbook["suggested_defaults"]
    assert shown["preference_semantics"].startswith("saved preferences describe")
    assert "automation" not in shown
    assert "integrations" not in shown


def test_payment_policy_and_capability_report_are_current_and_consistent() -> None:
    policy_files = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "AGENTS.md", ROOT / "docs" / "architecture.md"]
    for path in policy_files:
        text = path.read_text(encoding="utf-8")
        assert "Academia OS does not implement payments" in text
        assert "Agents must never infer payment authorization" in text or "agents must never infer payment authorization" in text
        assert "Never pay without explicit confirmation" not in text
    payment = next(item for item in capability_report()["prohibited"] if item["id"] == "payment")
    assert "not implemented" in payment["label"]
    assert "infer payment authorization" in payment["label"]


def test_ci_declares_read_only_repository_permissions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "cargo check --manifest-path frontend/src-tauri/Cargo.toml" in workflow
