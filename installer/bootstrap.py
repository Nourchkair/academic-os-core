#!/usr/bin/env python3
"""Create a personalized local Academic OS installation.

This wizard collects configuration only. It never asks for passwords, API keys,
OAuth tokens, browser cookies, or MFA codes. Integrations are authorized later
by the user in their own browser/account.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from installer.core import initialize_installation, load_manifest, validate_manifest
from academia_os.discovery import discover_academic_folders
from academia_os.semester import resolve_current_semester, semester_suggestions
from academia_os.timezones import detect_local_timezone


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _choose_academic_root() -> str:
    candidates = discover_academic_folders()
    default_root = str(Path.home() / "Desktop" / "University OS")
    if not candidates:
        return _ask("Where should your University folder live?", default_root)
    print("\nI found these likely academic folders:")
    for index, candidate in enumerate(candidates[:5], start=1):
        print(f"  {index}. {candidate.path} ({', '.join(candidate.reasons)})")
    choice = _ask("Choose a number, type another folder, or press Enter for the best match", "1").strip()
    if choice.isdigit() and 1 <= int(choice) <= min(len(candidates), 5):
        return str(candidates[int(choice) - 1].path)
    return choice or str(candidates[0].path)


def interactive_manifest() -> dict[str, Any]:
    print("Academic OS local setup")
    print("No passwords, tokens, cookies, or MFA codes are collected by this wizard.\n")
    root = _choose_academic_root()
    detected_timezone = detect_local_timezone() or "UTC"
    print(f"I detected your computer's time zone as {detected_timezone}.")
    timezone = _ask("Time zone (press Enter to use the detected one)", detected_timezone)
    install = str(Path.home() / ".academic-os")
    current_semester = resolve_current_semester(timezone_name=timezone)
    manifest = {
        "schema_version": 3,
        "student": {
            "name": _ask("Student name"),
            "institution": _ask("Institution"),
            "program": _ask("Program/faculty", "Not yet specified"),
        },
        "academic": {
            "semester": _ask("Current semester", current_semester),
            "timezone": timezone,
            "root_directory": root,
        },
        "runtime": {"install_directory": install},
        "preferences": {
            "explanation_style": _ask("Explanation style", "detailed"),
            "preferred_format": _ask("Preferred format", "markdown"),
            "use_visuals": _yes_no("Use diagrams/visual models", True),
            "study_method": _ask("Study method", "active recall"),
        },
        "acquisition": {
            "manual_import_enabled": True,
            "watched_folders": [],
            "browser_companion_enabled": False,
            "browser_access_enabled": False,
            "advanced_browser_enabled": False,
            "allowed_sites": [],
        },
        "privacy": {"browser_access_enabled": False, "allowed_sites": [], "dedicated_profile_recommended": True},
        "browser": {"name": "auto", "user_data_dir": "", "profile_directory": "", "access_enabled": False, "allowed_sites": []},
        "agents": {
            "hermes": {"enabled": _yes_no("Enable optional Hermes adapter", False), "profile": "default", "home_directory": str(Path.home() / ".hermes")},
            "codex": {"enabled": False},
            "claude": {"enabled": False},
            "chatgpt": {"enabled": False},
        },
    }
    return validate_manifest(manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="JSON manifest; omit for interactive setup")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allow-existing", action="store_true", help="Create missing files in an existing empty/template instance; never overwrite differing files")
    parser.add_argument("--print-manifest", action="store_true", help="Print the resolved manifest and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest) if args.manifest else interactive_manifest()
    if args.print_manifest:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    repo_root = args.repo_root.resolve()
    result = initialize_installation(
        manifest,
        template_root=repo_root / "templates" / "University",
        repo_root=repo_root,
        allow_existing=args.allow_existing,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\nNext steps:")
    print("1. Review the generated HANDOFF.md and Agent Setup Playbooks in the install directory.")
    print("2. Save desired Daily Academic Brief settings with `academia workflow set`; this changes only local preferences.")
    print("3. Ask an authorized external agent to implement any selected playbook and request the required permissions directly.")
    print("4. Run verify.py; no Academia scheduler or external account connection is enabled by this installer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
