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
from desktop.model import detect_local_timezone, discover_academic_folders, semester_suggestions


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
    default_root = str(Path.home() / "Desktop" / "University")
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
    hermes = str(Path.home() / ".hermes")
    manifest = {
        "schema_version": 1,
        "student": {
            "name": _ask("Student name"),
            "institution": _ask("Institution"),
            "program": _ask("Program/faculty", "Not yet specified"),
        },
        "academic": {
            "semester": _ask("Current semester", semester_suggestions()[0]),
            "timezone": timezone,
            "root_directory": root,
            "school_portal": _ask("School portal name", "Not yet specified"),
        },
        "preferences": {
            "explanation_style": _ask("Explanation style", "detailed"),
            "preferred_format": _ask("Preferred format", "markdown"),
            "use_visuals": _yes_no("Use diagrams/visual models", True),
            "study_method": _ask("Study method", "active recall"),
        },
        "integrations": {
            "gmail": _yes_no("Enable Gmail workflow", False),
            "calendar": _yes_no("Enable Google Calendar workflow", False),
            "drive": _yes_no("Enable Google Drive workflow", False),
            "school_portal": _yes_no("Enable school-portal/browser workflow", False),
        },
        "automation": {
            "daily_brief_enabled": _yes_no("Enable daily brief job", True),
            "daily_brief_time": _ask("Daily brief time (HH:MM)", "09:00"),
            "inbox_processor_enabled": _yes_no("Enable inbox processor job", True),
            "inbox_interval_minutes": int(_ask("Inbox polling interval in minutes", "5")),
        },
        "browser": {"name": "auto", "user_data_dir": "", "profile_directory": ""},
        "hermes": {"home_directory": hermes, "profile": "default", "install_directory": install},
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
    print("1. Review the generated HANDOFF.md in the install directory.")
    print("2. Authorize Google services directly in the user's own browser if enabled.")
    print("3. Sign into the school portal manually; never enter credentials into this wizard.")
    print("4. Run verify.py before enabling cron jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
