#!/usr/bin/env python3
"""Build a lightweight clickable Academia OS.app bundle on macOS.

The bundle keeps the local Python compatibility frontend and templates. It does not embed credentials, academic data, or require Hermes; the modern Tauri frontend is built separately. The recipient still needs Python 3 for this development bundle.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from academia_os.version import __version__
DIST = REPO_ROOT / "dist"
APP = DIST / "Academia OS.app"
RESOURCE_ROOT = APP / "Contents" / "Resources" / "academic-os-core"
MACOS_ROOT = APP / "Contents" / "MacOS"

EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "dist", ".venv", "node_modules", ".hermes", ".mypy_cache"}


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
    launcher = MACOS_ROOT / "AcademiaOS"
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
        "CFBundleDisplayName": "Academia OS",
        "CFBundleExecutable": "AcademiaOS",
        "CFBundleIdentifier": "com.academia.os.desktop",
        "CFBundleName": "Academia OS",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
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
