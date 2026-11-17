from __future__ import annotations

import json
from pathlib import Path

from tests.test_cli import run_cli

ROOT = Path(__file__).resolve().parents[1]


def test_knowledge_and_change_cli_round_trip(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    assert added.returncode == 0, added.stderr
    record = json.loads(added.stdout)

    migrated = run_cli(tmp_path, "knowledge", "migrate", "--semester", "Fall 2026", "--json")
    assert migrated.returncode == 0, migrated.stderr
    assert json.loads(migrated.stdout)["created_assertions"] == 1

    view = run_cli(tmp_path, "knowledge", "view", "--course", "POL 2103 - Politics", "--semester", "Fall 2026", "--json")
    assert view.returncode == 0, view.stderr
    assessment = json.loads(view.stdout)["assessments"][0]
    assert assessment["fields"]["due_date"]["value"] == "2026-11-12"
    assert assessment["fields"]["due_date"]["verification"] == "unverified"

    proposed = run_cli(
        tmp_path,
        "change", "propose-deadline", "--course", "POL 2103 - Politics",
        "--assessment", f"assessment:history:{record['id']}", "--new-date", "2026-11-20",
        "--source-kind", "student_report", "--semester", "Fall 2026", "--json",
    )
    assert proposed.returncode == 0, proposed.stderr
    changeset = json.loads(proposed.stdout)
    assert changeset["status"] == "proposed"
    assert changeset["operations"][0]["required"] is True

    approved = run_cli(tmp_path, "change", "approve", changeset["id"], "--semester", "Fall 2026", "--json")
    assert approved.returncode == 0, approved.stderr
    assert json.loads(approved.stdout)["status"] == "approved"

    executed = run_cli(tmp_path, "change", "execute", changeset["id"], "--semester", "Fall 2026", "--json")
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)["status"] == "verified"

    after = run_cli(tmp_path, "knowledge", "view", "--course", "POL 2103 - Politics", "--semester", "Fall 2026", "--json")
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout)["assessments"][0]["fields"]["due_date"]["value"] == "2026-11-20"

    reversed_result = run_cli(tmp_path, "change", "reverse", changeset["id"], "--semester", "Fall 2026", "--json")
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert json.loads(reversed_result.stdout)["status"] == "reverted"

    final = run_cli(tmp_path, "knowledge", "view", "--course", "POL 2103 - Politics", "--semester", "Fall 2026", "--json")
    assert final.returncode == 0, final.stderr
    assert json.loads(final.stdout)["assessments"][0]["fields"]["due_date"]["value"] == "2026-11-12"


def test_cli_rejects_agent_approval(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    record = json.loads(added.stdout)
    proposed = run_cli(
        tmp_path,
        "change", "propose-deadline", "--course", "POL 2103 - Politics",
        "--assessment", f"assessment:history:{record['id']}", "--new-date", "2026-11-20",
        "--semester", "Fall 2026", "--actor", "agent:codex", "--channel", "assistant", "--json",
    )
    assert proposed.returncode == 0, proposed.stderr
    changeset = json.loads(proposed.stdout)

    approved = run_cli(tmp_path, "change", "approve", changeset["id"], "--semester", "Fall 2026", "--actor", "agent:codex", "--channel", "assistant", "--json")
    assert approved.returncode == 2
    assert json.loads(approved.stdout)["type"] == "PermissionError"


def test_desktop_and_dashboard_contracts_include_the_change_slice() -> None:
    tauri = (ROOT / "frontend" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    history = (ROOT / "frontend" / "src" / "CourseworkHistory.tsx").read_text(encoding="utf-8")
    assert '"knowledge"' in tauri
    assert '"change"' in tauri
    assert '"propose-deadline"' in tauri
    assert '"reverse"' in tauri
    assert "proposeDeadlineChange" in api
    assert "approveChangeSet" in api
    assert "recoverChangeSets" in api
    assert "DeadlineChangeDialog" in history
    assert "Change deadline" in history
    assert '"intake"' in tauri
    assert '"paste"' in tauri
    assert "intakePaste" in api
    assert "intakePropose" in api
    assert "IntakeDialog" in (ROOT / "frontend" / "src" / "CoursesView.tsx").read_text(encoding="utf-8")
