#!/usr/bin/env python3
"""Normalize Tauri Action signatures for the Tauri updater runtime.

Tauri Action writes the raw minisign .sig text into latest.json. The updater
plugin expects that text wrapped in standard Base64, then decodes it before
minisign verification. Normalize every platform signature before publishing.
"""

from __future__ import annotations

import base64
import binascii
import json
import sys
from pathlib import Path


REQUIRED_TARGETS = ("darwin-aarch64", "darwin-x86_64")


def unwrap_signature(value: str, target: str) -> tuple[str, bool]:
    """Return decoded minisign text and whether the manifest value was wrapped."""
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
        wrapped = True
    except (binascii.Error, UnicodeDecodeError):
        decoded = value
        wrapped = False

    lines = [line.strip() for line in decoded.splitlines() if line.strip()]
    if (
        len(lines) < 4
        or not lines[0].startswith("untrusted comment:")
        or not lines[1].startswith("R")
        or not lines[2].startswith("trusted comment:")
    ):
        raise ValueError(f"{target} does not contain a complete minisign .sig payload")
    try:
        global_signature = base64.b64decode(lines[3], validate=True)
    except binascii.Error as exc:
        raise ValueError(f"{target} has an invalid Minisign global signature") from exc
    if len(global_signature) != 64:
        raise ValueError(f"{target} has an invalid Minisign global signature length")
    return decoded, wrapped


def normalize_manifest(path: Path) -> int:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict):
        raise ValueError("latest.json has no platforms object")

    missing = [target for target in REQUIRED_TARGETS if target not in platforms]
    if missing:
        raise ValueError(f"latest.json is missing targets: {', '.join(missing)}")

    for target, platform in platforms.items():
        if not isinstance(platform, dict):
            raise ValueError(f"{target} platform entry is invalid")
        signature = platform.get("signature")
        if not isinstance(signature, str) or not signature:
            raise ValueError(f"{target} has no signature")

        decoded, wrapped = unwrap_signature(signature, target)
        if not wrapped:
            platform["signature"] = base64.b64encode(decoded.encode("utf-8")).decode("ascii")

    # Verify the final representation the updater will decode.
    for target, platform in platforms.items():
        try:
            decoded = base64.b64decode(platform["signature"], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(f"{target} signature is not Base64-encoded UTF-8") from exc
        unwrap_signature(decoded, target)

    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(platforms)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: encode_updater_signatures.py PATH_TO_LATEST_JSON")
    count = normalize_manifest(Path(sys.argv[1]))
    print(f"UPDATER_SIGNATURES_OK: normalized {count} platform signatures")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
