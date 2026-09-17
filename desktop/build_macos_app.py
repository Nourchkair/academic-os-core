#!/usr/bin/env python3
"""Build a lightweight clickable Academic OS.app bundle on macOS.

The bundle keeps the same local Python implementation and templates. It does
not embed credentials or academic data. The recipient still needs Python 3 and
Hermes installed on their own computer.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dist"
APP = DIST / "Academic OS.app"
RESOURCE_ROOT = APP / "Contents" / "Resources" / "academic-os-core"
MACOS_ROOT = APP / "Contents" / "MacOS"

EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "dist", ".venv"}


def copy_repository() -> None:
    if APP.exists():
        shutil.rmtree(APP)
    RESOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    for source in REPO_ROOT.iterdir():
        if source.name in EXCLUDED_PARTS:
            continue
        destination = RESOURCE_ROOT / source.name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*EXCLUDED_PARTS))
        else:
            shutil.copy2(source, destination)


def write_launcher() -> None:
    MACOS_ROOT.mkdir(parents=True, exist_ok=True)
    launcher = MACOS_ROOT / "AcademicOS"
    launcher.write_text(
        """#!/bin/sh
set -eu
APP_ROOT=\"$(CDPATH= cd -- \"$(dirname -- \"$0\")/../Resources/academic-os-core\" && pwd)\"
if [ -n \"${ACADEMIC_OS_PYTHON:-}\" ]; then
  PYTHON=\"$ACADEMIC_OS_PYTHON\"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=\"$(command -v python3)\"
else
  osascript -e 'display alert \"Academic OS needs Python 3\" message \"Install Python 3, then reopen this app.\"'
  exit 1
fi
exec \"$PYTHON\" \"$APP_ROOT/desktop/app.py\" \"$@\"
""",
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_info_plist() -> None:
    contents = APP / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    plist = {
        "CFBundleDisplayName": "Academic OS",
        "CFBundleExecutable": "AcademicOS",
        "CFBundleIdentifier": "local.academic-os.desktop",
        "CFBundleName": "Academic OS",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)


def main() -> int:
    if os.uname().sysname != "Darwin":
        raise SystemExit("The .app bundle builder is for macOS; run the desktop app directly on other platforms.")
    DIST.mkdir(parents=True, exist_ok=True)
    copy_repository()
    write_launcher()
    write_info_plist()
    print(APP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
