from __future__ import annotations

import json
from pathlib import Path

from tests.test_cli import run_cli


def test_intake_paste_resolve_propose_and_execute_cli(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    assert added.returncode == 0, added.stderr
    record = json.loads(added.stdout)

    pasted = run_cli(
        tmp_path,
        "intake", "paste", "--course", "POL 2103 - Politics",
        "--text", "My professor moved the Second Essay deadline to November 20.",
        "--source-kind", "professor_announcement", "--semester", "Fall 2026", "--json",
    )
    assert pasted.returncode == 0, pasted.stderr
    result = json.loads(pasted.stdout)
    candidate = result["candidates"][0]
    assert candidate["status"] == "resolved"
    assert candidate["value"] == "2026-11-20"
    assert candidate["resolution"]["assessment_id"] == f"assessment:history:{record['id']}"

    proposed = run_cli(tmp_path, "intake", "propose", candidate["id"], "--semester", "Fall 2026", "--json")
    assert proposed.returncode == 0, proposed.stderr
    changeset = json.loads(proposed.stdout)
    assert changeset["status"] == "proposed"

    approved = run_cli(tmp_path, "change", "approve", changeset["id"], "--semester", "Fall 2026", "--json")
    assert approved.returncode == 0, approved.stderr
    executed = run_cli(tmp_path, "change", "execute", changeset["id"], "--semester", "Fall 2026", "--json")
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)["status"] == "verified"

    listed = run_cli(tmp_path, "intake", "list", "--semester", "Fall 2026", "--json")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["candidates"][0]["status"] == "proposed"


def test_intake_resolve_cli_for_ambiguous_assessment(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    record = json.loads(added.stdout)
    pasted = run_cli(
        tmp_path,
        "intake", "paste", "--course", "POL 2103 - Politics",
        "--text", "The professor moved the Final Essay deadline to November 20.",
        "--semester", "Fall 2026", "--json",
    )
    candidate = json.loads(pasted.stdout)["candidates"][0]
    assert candidate["status"] == "needs_entity"

    resolved = run_cli(
        tmp_path,
        "intake", "resolve", candidate["id"],
        "--assessment", f"assessment:history:{record['id']}", "--semester", "Fall 2026", "--json",
    )
    assert resolved.returncode == 0, resolved.stderr
    assert json.loads(resolved.stdout)["candidate"]["status"] == "resolved"


def test_intake_agent_cannot_resolve(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    record = json.loads(added.stdout)
    pasted = run_cli(
        tmp_path,
        "intake", "paste", "--course", "POL 2103 - Politics",
        "--text", "The Second Essay deadline moved to November 20.",
        "--semester", "Fall 2026", "--json",
    )
    candidate = json.loads(pasted.stdout)["candidates"][0]
    result = run_cli(
        tmp_path,
        "intake", "resolve", candidate["id"],
        "--assessment", f"assessment:history:{record['id']}", "--semester", "Fall 2026",
        "--actor", "agent:codex", "--channel", "dashboard", "--json",
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["type"] == "PermissionError"


def test_intake_document_cli_scans_an_imported_markdown_file(tmp_path) -> None:
    added = run_cli(
        tmp_path,
        "history", "add", "--course", "POL 2103 - Politics", "--kind", "essay", "--title", "Second Essay",
        "--status", "planned", "--due-date", "2026-11-12", "--semester", "Fall 2026", "--json",
    )
    assert added.returncode == 0, added.stderr
    record = json.loads(added.stdout)
    root = tmp_path / "University OS"
    document = root / "Fall 2026" / "POL 2103 - Politics" / "00_INBOX" / "announcement.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("The professor moved the Second Essay deadline to November 20.\n", encoding="utf-8")
    relative = document.relative_to(root).as_posix()

    result = run_cli(
        tmp_path,
        "intake", "document", "--course", "POL 2103 - Politics",
        "--source", relative, "--semester", "Fall 2026", "--json",
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    candidate = value["candidates"][0]
    assert value["intake"]["source_kind"] == "imported_document"
    assert candidate["status"] == "resolved"
    assert candidate["resolution"]["assessment_id"] == f"assessment:history:{record['id']}"
