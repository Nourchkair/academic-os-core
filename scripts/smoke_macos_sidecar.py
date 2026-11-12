#!/usr/bin/env python3
"""Exercise a packaged Academia CLI against a disposable local workspace."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from academia_os.config import save_config  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_macos_sidecar.py /path/to/academia", file=sys.stderr)
        return 2

    cli = Path(sys.argv[1]).resolve()
    if not cli.is_file() or not cli.stat().st_mode & 0o111:
        print(f"Academia CLI is missing or not executable: {cli}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="academia-sidecar-smoke-") as temporary:
        root = Path(temporary)
        workspace = root / "University"
        semester = workspace / "Fall 2026"
        semester.mkdir(parents=True)
        (workspace / "ACADEMIC_OS_RULES.md").write_text("Disposable release smoke fixture.\n", encoding="utf-8")
        (workspace / "COURSE_TEMPLATE").mkdir()

        profile = root / "runtime" / "profile.json"
        config = {
            "schema_version": 3,
            "student": {"name": "Release Smoke", "institution": "Academia OS", "program": ""},
            "academic": {
                "semester": "Fall 2026",
                "timezone": "UTC",
                "root_directory": str(workspace),
            },
            "runtime": {"install_directory": str(root / "runtime")},
            "preferences": {
                "explanation_style": "detailed",
                "preferred_format": "markdown",
                "use_visuals": True,
                "study_method": "active recall",
            },
            "acquisition": {"manual_import_enabled": True, "watched_folders": [], "browser_companion_enabled": False},
            "privacy": {"dedicated_profile_recommended": True},
            "agents": {
                "hermes": {"enabled": False, "profile": "default", "home_directory": ""},
                "codex": {"enabled": False},
                "claude": {"enabled": False},
                "chatgpt": {"enabled": False},
            },
            "browser": {"name": "auto", "user_data_dir": "", "profile_directory": "", "access_enabled": False, "allowed_sites": []},
        }
        save_config(profile, config)

        try:
            result = subprocess.run(
                [str(cli), "--profile", str(profile), "status", "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            print("Bundled Academia CLI did not finish `status --json` within 90 seconds.", file=sys.stderr)
            return 1

        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            print(f"Bundled Academia CLI failed `status --json`: {detail}", file=sys.stderr)
            return 1
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            print(f"Bundled Academia CLI returned invalid JSON: {error}", file=sys.stderr)
            return 1

        snapshot = payload.get("workspace") if isinstance(payload, dict) else None
        if not isinstance(snapshot, dict) or snapshot.get("workspace_exists") is not True:
            print("Bundled Academia CLI did not recognize the disposable workspace in `status --json`.", file=sys.stderr)
            return 1
        if Path(str(snapshot.get("academic_root", ""))).resolve() != workspace.resolve():
            print("Bundled Academia CLI returned a workspace path different from the disposable fixture.", file=sys.stderr)
            return 1

        if os.environ.get("ACADEMIA_REQUIRE_GOOGLE_CLIENT") == "1":
            google = subprocess.run(
                [str(cli), "--profile", str(profile), "connectors", "google", "status", "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            try:
                google_status = json.loads(google.stdout) if google.returncode == 0 else {}
            except json.JSONDecodeError:
                google_status = {}
            if not isinstance(google_status, dict) or google_status.get("auth_status") != "configured" or not google_status.get("client_id"):
                detail = google.stderr.strip() or google.stdout.strip() or "client configuration was not found"
                print(f"Packaged Google OAuth client bootstrap failed: {detail}", file=sys.stderr)
                return 1

        print(f"SIDECAR_STATUS_OK: Academia {payload.get('version', 'unknown')} read a disposable local workspace.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
