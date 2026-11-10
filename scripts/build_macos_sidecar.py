#!/usr/bin/env python3
"""Build the native-architecture Academia CLI binary used inside Tauri bundles."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "frontend" / "src-tauri"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=TAURI / "binaries")
    args = parser.parse_args()

    try:
        import PyInstaller.__main__
    except ImportError:
        parser.error("PyInstaller is required; install the desktop-build extra with `python -m pip install -e '.[desktop-build]'`.")

    target_result = subprocess.run(
        ["rustc", "--print", "host-tuple"], capture_output=True, text=True, check=False
    )
    target = target_result.stdout.strip()
    if target_result.returncode or not target:
        rustc_info = subprocess.run(["rustc", "-Vv"], capture_output=True, text=True, check=True).stdout
        target = next((line.partition(":")[2].strip() for line in rustc_info.splitlines() if line.startswith("host:")), "")
    if not target:
        parser.error("rustc did not report a host target triple")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"academia-{target}"
    with tempfile.TemporaryDirectory(prefix="academia-sidecar-") as work_dir:
        work = Path(work_dir)
        data_args = [
            (ROOT / "academia_os", "academia_os"),
            (ROOT / "templates", "templates"),
            (ROOT / "runtime", "runtime"),
            (ROOT / "adapters", "adapters"),
            (ROOT / "docs" / "local-installation-handoff.md", "docs"),
        ]
        options = [
            str(ROOT / "scripts" / "academia_sidecar_entry.py"),
            "--name=academia",
            "--onefile",
            "--clean",
            f"--distpath={work / 'dist'}",
            f"--workpath={work / 'build'}",
            f"--specpath={work}",
            f"--paths={ROOT}",
            "--collect-submodules=academia_os",
            "--collect-submodules=installer",
            "--collect-submodules=adapters",
            "--hidden-import=zoneinfo",
        ]
        for source, destination_name in data_args:
            options.append(f"--add-data={source}{os.pathsep}{destination_name}")
        import PyInstaller.__main__

        PyInstaller.__main__.run(options)
        produced = work / "dist" / "academia"
        if not produced.is_file():
            parser.error("PyInstaller did not produce the expected Academia executable")
        shutil.copy2(produced, destination)
        destination.chmod(destination.stat().st_mode | 0o111)

        # Exercise an actual local-workspace command before packaging. The
        # helper uses a disposable workspace and profile, never the user's data.
        smoke = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_macos_sidecar.py"), str(destination)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if smoke.returncode:
            detail = smoke.stderr.strip() or smoke.stdout.strip() or f"exit code {smoke.returncode}"
            parser.error(f"Academia sidecar failed its workspace status check: {detail}")
        print(smoke.stdout.strip())

    print(f"Built {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
