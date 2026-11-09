#!/usr/bin/env python3
"""Insert the release public key into Tauri config on an ephemeral CI runner."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "frontend" / "src-tauri" / "tauri.conf.json"


def main() -> int:
    public_key = os.environ.get("TAURI_UPDATER_PUBLIC_KEY", "").strip()
    key_lines = [line.strip() for line in public_key.splitlines() if line.strip()]
    if len(key_lines) < 2 or not key_lines[0].startswith("untrusted comment:") or not key_lines[1].startswith("RW"):
        raise SystemExit("Set the GitHub Actions variable or secret TAURI_UPDATER_PUBLIC_KEY to the full public key from `tauri signer generate`.")

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config.setdefault("plugins", {}).setdefault("updater", {})["pubkey"] = public_key
    config.setdefault("bundle", {})["createUpdaterArtifacts"] = True
    CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
