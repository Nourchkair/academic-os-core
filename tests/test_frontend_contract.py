from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend" / "src"


def test_settings_is_local_setup_only() -> None:
    source = (FRONTEND / "SettingsView.tsx").read_text(encoding="utf-8")
    assert 'SettingsSection title="Profile"' in source
    assert 'SettingsSection title="Workspace"' in source
    assert '<h4>Sources & imports</h4>' not in source
    assert 'manualImport' not in source
    assert 'watchedFolders' not in source
    assert "Automation ownership" not in source
    assert "External access guard" not in source
    assert "Agent access (optional)" not in source
    assert "browserEnabled" not in source
    assert "capabilities" not in source


def test_dashboard_has_semester_courses_library_and_activity_surfaces() -> None:
    source = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    assert "{ id: 'activity', label: 'Activity'" in source
    assert "function ActivityView" in source
    assert "<CoursesView" in source
    assert "<ActionPanel" in source
    assert "profile-action" not in source
    assert "workspace-action-button" in source
    assert ">+</button>" in source
    assert "{ id: 'library'" not in source
    assert "{ id: 'import'" not in source
    assert "{ id: 'review'" not in source
    assert "const title = nav.find" not in source
    assert "<h1>{title}</h1>" not in source

    courses = (FRONTEND / "CoursesView.tsx").read_text(encoding="utf-8")
    assert "Choose a semester" in courses
    assert "Syllabi & guides" in courses
    assert "Readings & references" in courses
    assert "api.filePreview(item.path, item.semester)" in courses


def test_action_panel_owns_import_and_migration_without_review_navigation() -> None:
    source = (FRONTEND / "ActionPanel.tsx").read_text(encoding="utf-8")
    assert "Import material" in source
    assert "Migrate older material" in source
    assert "<ImportView" in source
    assert "<MigrationView" in source
    assert "action-panel-heading" in source
    assert "Review" not in source


def test_sidebar_is_fixed_on_desktop_and_normal_flow_on_mobile() -> None:
    source = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert ".sidebar { bottom: 0; height: 100vh;" in source
    assert "position: fixed" in source
    assert ".main-content { margin-left: 246px;" in source
    assert "position: static" in source


def test_onboarding_does_not_present_browser_or_agent_configuration() -> None:
    source = (FRONTEND / "Onboarding.tsx").read_text(encoding="utf-8")
    assert "Interface note" in source
    assert "function InterfaceNote" in source
    assert "<strong>Browser access</strong>" not in source
    assert '<SummaryRow label="Browser access"' not in source
    assert "function Agents" not in source
