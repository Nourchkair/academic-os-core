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
    assert "{ id: 'review', label: 'Review'" in source
    assert "function ActivityView" in source
    assert "<ReviewView" in source
    assert "<CoursesView" in source
    assert "<ActionPanel" in source
    assert "profile-action" not in source
    assert "<HomeView" in source
    assert "{ id: 'library'" not in source
    assert "{ id: 'import'" not in source
    assert "const title = nav.find" not in source
    assert "<h1>{title}</h1>" not in source

    courses = (FRONTEND / "CoursesView.tsx").read_text(encoding="utf-8")
    assert "Choose a semester" in courses
    assert "Syllabi & guides" in courses
    assert "Readings & references" in courses
    assert "AI-created material" not in courses
    assert "AI-generated" not in courses
    assert "api.filePreview(item.path, item.semester)" in courses

    home = (FRONTEND / "HomeView.tsx").read_text(encoding="utf-8")
    assert "Open decisions" in home
    assert "Needs input" not in home
    assert '<p className="eyebrow">Intake</p>' in home
    assert "onClick={() => onNavigate('activity')}" in home


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


def test_settings_exposes_connections_without_agent_setup_playbooks() -> None:
    source = (FRONTEND / "SettingsView.tsx").read_text(encoding="utf-8")
    assert "Agent setup playbooks" not in source
    assert "EnhanceSetup" not in source
    assert "PlaybookPanel" not in source
    assert "api.playbooks" not in source
    assert "workflowPreferences" not in source
    assert "ConnectionsHub" in source
    assert "GoogleConnectorCard" in (FRONTEND / "ConnectionsHub.tsx").read_text(encoding="utf-8")
    assert "Gmail and Google Calendar" in (FRONTEND / "ConnectionsHub.tsx").read_text(encoding="utf-8")
    assert "Connect Brightspace" not in source
    assert "Automation enabled" not in source

def test_tasks_surface_does_not_render_the_task_definition_explanation_block() -> None:
    source = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
    assert "task-definition-card" not in source
    assert "What becomes a task" not in source
    assert "Only two sources create tasks here" not in source


def test_each_course_has_a_durable_assignment_and_project_history_surface() -> None:
    courses = (FRONTEND / "CoursesView.tsx").read_text(encoding="utf-8")
    history = (FRONTEND / "CourseworkHistory.tsx").read_text(encoding="utf-8")
    api = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "course-section-tabs" in courses
    assert "CourseworkHistoryView" in courses
    assert "Add history item" in history
    assert "Assignments & projects" in history
    assert "Course-relative file paths" in history
    assert "api.courseworkHistory(course.id, semester)" in history
    assert "api.updateCourseworkHistory" in history
    assert "This records coursework in your local workspace" in history
    assert "history', ['list', '--course', courseId, '--semester', semester]" in api
