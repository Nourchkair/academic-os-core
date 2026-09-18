from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from academia_os.config import save_config
from academia_os.recommendations import get_recipe
from academia_os.web import SAFE_COMMANDS
from academia_os.workflow_preferences import WorkflowPreferencesStore
from tests.test_agent_neutral_core import minimal_config


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def configured_profile(tmp_path: Path) -> tuple[Path, Path]:
    config = minimal_config(tmp_path)
    profile = Path(config["runtime"]["install_directory"]) / "profile.json"
    save_config(profile, config)
    return profile, Path(config["academic"]["root_directory"])


def run_cli(profile: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "academia_os", "--profile", str(profile), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_workflow_preferences_save_read_and_list_with_user_and_agent_attribution(tmp_path: Path) -> None:
    _, root = configured_profile(tmp_path)
    store = WorkflowPreferencesStore(root)

    assert store.list() == []
    user_saved = store.set(
        "daily_academic_brief",
        preferences={"time": "08:30", "cadence": "weekdays", "include_calendar": True},
        custom_instructions="Keep the briefing short.",
        external_setup_notes="Managed by my external AI agent.",
        updated_by="user",
    )

    assert user_saved["workflow_id"] == "daily_academic_brief"
    assert user_saved["preferences"] == {"time": "08:30", "cadence": "weekdays", "include_calendar": True}
    assert user_saved["updated_by"] == "user"
    assert len(store.list()) == 1
    assert store.get_saved("daily_academic_brief") == user_saved
    assert (root / ".academia" / "workflow_preferences.json").is_file()

    agent_saved = store.set(
        "daily_academic_brief",
        preferences={"detail": "standard"},
        custom_instructions="Prioritize the next three days.",
        updated_by="agent:codex",
    )
    assert agent_saved["updated_by"] == "agent:codex"
    assert agent_saved["preferences"] == {"time": "08:30", "cadence": "weekdays", "include_calendar": True, "detail": "standard"}
    assert store.get_saved("daily_academic_brief")["external_setup_notes"] == "Managed by my external AI agent."


def test_workflow_show_returns_recipe_saved_overrides_and_effective_defaults(tmp_path: Path) -> None:
    _, root = configured_profile(tmp_path)
    store = WorkflowPreferencesStore(root)
    store.set("daily_academic_brief", preferences={"time": "08:30", "include_calendar": True}, updated_by="user")

    value = store.show("daily_academic_brief")

    assert value["recommended_playbook"]["kind"] == "agent_setup_playbook"
    assert value["recommended_playbook"]["execution_owner"] == "external_agent"
    assert value["recommended_recipe"]["suggested_defaults"]["time"] == "09:00"
    assert value["saved_preferences"]["preferences"] == {"time": "08:30", "include_calendar": True}
    assert value["effective_preferences"]["time"] == "08:30"
    assert value["effective_preferences"]["cadence"] == "daily"
    assert value["effective_preferences"]["include_calendar"] is True

    value["recommended_recipe"]["suggested_defaults"]["time"] = "01:00"
    assert get_recipe("daily_academic_brief")["suggested_defaults"]["time"] == "09:00"


def test_workflow_preferences_unknown_ids_and_invalid_values_are_rejected_without_writing(tmp_path: Path) -> None:
    _, root = configured_profile(tmp_path)
    store = WorkflowPreferencesStore(root)

    with pytest.raises(KeyError, match="unknown recommended workflow"):
        store.set("not_a_real_workflow", preferences={"time": "08:30"}, updated_by="user")
    with pytest.raises(ValueError, match="preference"):
        store.set("daily_academic_brief", preferences={"not_a_recipe_option": True}, updated_by="user")
    with pytest.raises(ValueError, match="HH:MM"):
        store.set("daily_academic_brief", preferences={"time": "8:30"}, updated_by="user")
    with pytest.raises(ValueError, match="updated_by"):
        store.set("daily_academic_brief", preferences={}, updated_by="not-authenticated")
    assert not (root / ".academia" / "workflow_preferences.json").exists()


def test_workflow_preferences_reject_credential_like_fields_and_notes(tmp_path: Path) -> None:
    _, root = configured_profile(tmp_path)
    store = WorkflowPreferencesStore(root)

    with pytest.raises(ValueError, match="credential"):
        store.set("daily_academic_brief", preferences={"api_key": "secret"}, updated_by="user")
    with pytest.raises(ValueError, match="credential"):
        store.set("daily_academic_brief", external_setup_notes="password=super-secret", updated_by="user")
    with pytest.raises(ValueError, match="credential"):
        store.set("daily_academic_brief", custom_instructions="Use Bearer abcdefghijklmnopqrstuvwxyz", updated_by="user")
    assert not (root / ".academia" / "workflow_preferences.json").exists()


def test_workflow_preference_cli_reads_and_writes_same_local_state(tmp_path: Path) -> None:
    profile, root = configured_profile(tmp_path)

    before = run_cli(profile, "workflow", "preferences", "--json")
    assert before.returncode == 0, before.stderr
    assert json.loads(before.stdout) == {"schema_version": 1, "workflows": []}
    assert not (root / ".academia").exists()

    saved = run_cli(
        profile,
        "workflow",
        "set",
        "daily_academic_brief",
        "--set",
        "time=08:30",
        "--set",
        "cadence=weekdays",
        "--set",
        "include_calendar=true",
        "--set",
        "include_academic_email=true",
        "--set",
        "check_course_sources_first=true",
        "--custom-instructions",
        "Keep it short and prioritize the next three days.",
        "--external-setup-notes",
        "Managed by my external AI agent.",
        "--updated-by",
        "agent:codex",
        "--json",
    )
    assert saved.returncode == 0, saved.stderr
    saved_value = json.loads(saved.stdout)
    assert saved_value["saved_preferences"]["updated_by"] == "agent:codex"
    assert saved_value["effective_preferences"]["time"] == "08:30"
    assert saved_value["effective_preferences"]["cadence"] == "weekdays"
    assert saved_value["effective_preferences"]["include_calendar"] is True
    assert saved_value["recommended_playbook"]["kind"] == "agent_setup_playbook"
    assert saved_value["recommended_recipe"]["suggested_defaults"]["time"] == "09:00"

    shown = run_cli(profile, "workflow", "show", "daily_academic_brief", "--json")
    assert shown.returncode == 0, shown.stderr
    shown_value = json.loads(shown.stdout)
    assert shown_value["saved_preferences"]["preferences"]["time"] == "08:30"
    assert shown_value["effective_preferences"]["include_academic_email"] is True
    rendered = json.dumps(shown_value).lower()
    assert '"gmail_connected"' not in rendered
    assert '"calendar_connected"' not in rendered
    assert '"automation_enabled"' not in rendered

    listed = run_cli(profile, "workflow", "preferences", "--json")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.count("daily_academic_brief") == 1


def test_workflow_preference_cli_rejects_unknown_workflow_and_recipe_commands_stay_read_only(tmp_path: Path) -> None:
    profile, root = configured_profile(tmp_path)
    unknown = run_cli(profile, "workflow", "show", "unknown_workflow", "--json")
    assert unknown.returncode == 2
    assert json.loads(unknown.stdout)["type"] == "KeyError"

    recommendations = run_cli(profile, "agent", "recommendations", "--json")
    recipe = run_cli(profile, "agent", "recipe", "daily_academic_brief", "--json")
    assert recommendations.returncode == 0
    assert recipe.returncode == 0
    assert not (root / ".academia").exists()


def test_dashboard_exposes_agent_setup_playbooks_and_editable_preferences_without_connection_controls() -> None:
    source = (FRONTEND / "SettingsView.tsx").read_text(encoding="utf-8")
    tauri = (FRONTEND.parent / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "workflow" in SAFE_COMMANDS
    assert '"workflow"' in tauri
    assert "Playbook guide" in source
    assert "My playbook preferences" in source
    assert "Save my playbook preferences" in source
    assert "workflowPreferences" in source
    assert "workflowSet" in source
    assert "Agent Setup Playbook" in source
    assert "api.playbooks" in source
    assert "Connect Gmail" not in source
    assert "Connect Calendar" not in source
    assert "automation definitely running" not in source


def test_capability_labels_capitalize_words_after_underscore_conversion() -> None:
    source = (FRONTEND / "SettingsView.tsx").read_text(encoding="utf-8")
    assert "function capabilityLabel" in source
    assert "replaceAll('_', ' ')" in source
    assert "replace(/\\b\\w/g" in source
    assert "toUpperCase()" in source
