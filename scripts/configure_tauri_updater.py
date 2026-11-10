#!/usr/bin/env python3
"""Insert the release public key into Tauri config on an ephemeral CI runner."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "frontend" / "src-tauri" / "tauri.conf.json"


def main() -> int:
    public_key = os.environ.get("TAURI_UPDATER_PUBLIC_KEY", "").strip()
    try:
        decoded_key = base64.b64decode(public_key, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise SystemExit("Set TAURI_UPDATER_PUBLIC_KEY to the exact base64 contents of the Tauri-generated public-key file.")

    key_lines = [line.strip() for line in decoded_key.splitlines() if line.strip()]
    if len(key_lines) < 2 or not key_lines[0].startswith("untrusted comment:") or not key_lines[1].startswith("RW"):
        raise SystemExit("TAURI_UPDATER_PUBLIC_KEY must decode to the minisign public-key comment and RW key line.")

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config.setdefault("plugins", {}).setdefault("updater", {})["pubkey"] = public_key
    config.setdefault("bundle", {})["createUpdaterArtifacts"] = True
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
