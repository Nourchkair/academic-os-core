#!/usr/bin/env python3
"""Build the native-architecture Academia CLI binary used inside Tauri bundles."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "frontend" / "src-tauri"


def google_oauth_client_config() -> dict[str, Any] | None:
    """Read app-level Google OAuth config without printing or persisting secrets.

    Release CI should provide ``ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64`` as a
    repository secret. Local developers can use ``ACADEMIA_GOOGLE_CLIENT_JSON``
    or the client already held in the macOS Keychain.
    """
    encoded = os.environ.get("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64")
    path = os.environ.get("ACADEMIA_GOOGLE_CLIENT_JSON")
    value: Any = None
    if encoded:
        try:
            raw = base64.b64decode(encoded, validate=True)
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ACADEMIA_GOOGLE_OAUTH_CLIENT_JSON_B64 is not valid base64-encoded JSON") from exc
    elif path:
        try:
            value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("ACADEMIA_GOOGLE_CLIENT_JSON could not be read as JSON") from exc
    else:
        try:
            import keyring

            stored = keyring.get_password("academia-os-google-oauth", "client")
            value = json.loads(stored) if stored else None
        except ImportError:
            value = None
        except Exception as exc:
            if os.environ.get("ACADEMIA_REQUIRE_GOOGLE_CLIENT") == "1":
                raise ValueError("Google OAuth client could not be read from the system credential store") from exc
            value = None

    if value is None:
        if os.environ.get("ACADEMIA_REQUIRE_GOOGLE_CLIENT") == "1":
            raise ValueError("Google OAuth client is required for this packaged build")
        return None
    client = value.get("installed") if isinstance(value, dict) else None
    if not isinstance(client, dict) and isinstance(value, dict):
        client = value.get("web")
    if not isinstance(client, dict):
        client = value if isinstance(value, dict) else None
    client_id = client.get("client_id") if isinstance(client, dict) else None
    client_secret = client.get("client_secret") if isinstance(client, dict) else None
    if not isinstance(client_id, str) or not client_id.strip() or not isinstance(client_secret, str) or not client_secret.strip():
        raise ValueError("Google OAuth client JSON must contain a client id and client secret")
    return {"installed": {"client_id": client_id.strip(), "client_secret": client_secret.strip()}}


def stage_google_oauth_client(work_dir: Path, client: dict[str, Any]) -> Path:
    """Write a private, build-temporary client resource for PyInstaller."""
    path = Path(work_dir) / "google_client" / "client.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(client, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)
    return path


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
        try:
            google_client = google_oauth_client_config()
        except ValueError as exc:
            parser.error(str(exc))
        if google_client is not None:
            client_resource = stage_google_oauth_client(work, google_client)
            data_args.append((client_resource, "google_client"))
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
