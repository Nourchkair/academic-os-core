from __future__ import annotations

from pathlib import Path

import pytest

from academia_os import codex_connect


def config(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "config.toml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return path


def test_connect_preserves_other_servers_and_creates_a_backup(tmp_path: Path) -> None:
    path = config(tmp_path, '[mcp_servers.aside]\ncommand = "/usr/bin/aside"\nargs = ["mcp"]\n')
    profile = tmp_path / "profile.json"

    value = codex_connect.connect(profile, ["tasks", "history", "study"], config_path=path)

    assert value["connected"] is True
    assert value["selected_actions"] == ["tasks", "history", "study"]
    assert value["backup_path"]
    assert Path(value["backup_path"]).is_file()
    text = path.read_text(encoding="utf-8")
    assert "[mcp_servers.aside]" in text
    assert "[mcp_servers.academia]" in text
    assert text.count("[mcp_servers.academia]") == 1
    assert "--allow-action" in text
    assert 'default_tools_approval_mode = "approve"' in text
    assert value["matches_current_install"] is True


def test_reconnect_replaces_only_the_academia_section(tmp_path: Path) -> None:
    path = config(tmp_path, '[mcp_servers.aside]\ncommand = "/usr/bin/aside"\nargs = ["mcp"]\n')
    profile = tmp_path / "profile.json"
    first = codex_connect.connect(profile, ["tasks"], config_path=path)
    second = codex_connect.connect(profile, ["tasks", "imports"], config_path=path)

    text = path.read_text(encoding="utf-8")
    assert text.count("[mcp_servers.academia]") == 1
    assert "[mcp_servers.aside]" in text
    assert second["allow_actions"] == ["tasks", "imports"]
    assert second["backup_path"] and second["backup_path"] != first["backup_path"]


def test_disconnect_removes_only_academia(tmp_path: Path) -> None:
    path = config(tmp_path, '[mcp_servers.aside]\ncommand = "/usr/bin/aside"\nargs = ["mcp"]\n')
    profile = tmp_path / "profile.json"
    codex_connect.connect(profile, ["tasks"], config_path=path)

    value = codex_connect.disconnect(config_path=path)

    assert value["connected"] is False
    text = path.read_text(encoding="utf-8")
    assert "[mcp_servers.aside]" in text
    assert "[mcp_servers.academia]" not in text


def test_connect_rejects_unknown_actions_and_invalid_toml(tmp_path: Path) -> None:
    path = config(tmp_path, "not valid toml [")
    with pytest.raises(ValueError, match="valid TOML"):
        codex_connect.connect(tmp_path / "profile.json", ["tasks"], config_path=path)

    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        codex_connect.connect(tmp_path / "profile.json", ["everything"], config_path=path)
    defaulted = codex_connect.connect(tmp_path / "profile.json", [], config_path=path)
    assert defaulted["allow_actions"] == list(codex_connect.DEFAULT_ACTIONS)


def test_connect_updates_quoted_and_commented_headers(tmp_path: Path) -> None:
    path = config(tmp_path, '[mcp_servers."academia"] # local server\ncommand = "/old/python"\nargs = []\n')
    value = codex_connect.connect(tmp_path / "profile.json", ["tasks"], config_path=path)

    text = path.read_text(encoding="utf-8")
    assert value["connected"] is True
    assert '[mcp_servers."academia"]' not in text
    assert text.count("[mcp_servers.academia]") == 1
    assert 'command = "/old/python"' not in text

    codex_connect.disconnect(config_path=path)
    assert "academia" not in path.read_text(encoding="utf-8")


def test_command_keeps_the_virtual_environment_symlink(tmp_path: Path, monkeypatch) -> None:
    import sys

    real = tmp_path / "python-real"
    real.write_text("", encoding="utf-8")
    link = tmp_path / "python"
    link.symlink_to(real)
    monkeypatch.setattr(sys, "executable", str(link))

    command, args, environment = codex_connect._academia_command(tmp_path / "profile.json")

    assert command == str(link)
    assert command != str(real)
    assert command.endswith("python")
    assert args[:2] == ["-m", "academia_os"]
    assert environment["PYTHONPATH"]


def test_codex_installed_checks_common_gui_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(codex_connect.shutil, "which", lambda command, path=None: "/opt/homebrew/bin/codex" if path and "/opt/homebrew/bin" in path else None)
    assert codex_connect._codex_installed() is True
