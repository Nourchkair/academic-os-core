from __future__ import annotations

import pytest

from academia_os.transport_policy import SAFE_COMMANDS, validate_command


def test_shared_allowlist_contains_expected_read_and_write_surfaces() -> None:
    assert "status" in SAFE_COMMANDS
    assert "study" in SAFE_COMMANDS
    assert "settings" in SAFE_COMMANDS
    assert "dashboard" not in SAFE_COMMANDS
    assert "desktop-bridge" not in SAFE_COMMANDS
    assert "mcp" not in SAFE_COMMANDS
    assert "backup" not in SAFE_COMMANDS


def test_valid_commands_and_arguments_are_returned_unchanged() -> None:
    command, args = validate_command("status", ["--timezone", "UTC"])
    assert command == "status"
    assert args == ["--timezone", "UTC"]
    assert validate_command("study", ["context", "--course", "POL 2103", "--deep"])[1] == ["context", "--course", "POL 2103", "--deep"]


def test_unknown_commands_fail_closed() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_command("dashboard", [])
    with pytest.raises(ValueError, match="not allowed"):
        validate_command("backup", ["create", "/tmp/backup.zip"])


def test_processing_transport_is_read_only() -> None:
    assert validate_command("process", ["status"])[1] == ["status"]
    for args in (["batch"], ["retry", "abc"], ["forget", "abc"], ["run", "abc"], ["status", "--semester", "Fall 2026"]):
        with pytest.raises(ValueError, match="only read processing status"):
            validate_command("process", args)


def test_profile_json_and_nul_arguments_are_rejected() -> None:
    for args in (["--profile", "other.json"], ["--profile=other.json"], ["--json"], ["--output=x\0y"]):
        with pytest.raises(ValueError):
            validate_command("status", args)


def test_argument_count_and_length_are_bounded() -> None:
    with pytest.raises(ValueError, match="at most 2"):
        validate_command("status", ["a", "b", "c"], max_arguments=2)
    with pytest.raises(ValueError, match="limited to 3"):
        validate_command("status", ["abcd"], max_argument_length=3)
    with pytest.raises(ValueError, match="array"):
        validate_command("status", "not-a-list")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="array of strings"):
        validate_command("status", [1])  # type: ignore[list-item]
