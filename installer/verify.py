#!/usr/bin/env python3
"""Verify a generated Academic OS installation without touching user data."""
from __future__ import annotations

import argparse
import json
import py_compile
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from installer.core import load_manifest

REQUIRED_ROOT_FILES = {
    "README.md",
    "ACADEMIC_OS_RULES.md",
    "INTEGRATION_STATUS.md",
    "VERIFICATION.md",
    "COURSE_TEMPLATE/README.md",
    "COURSE_TEMPLATE/01_COURSE/README.md",
    "COURSE_TEMPLATE/00_INBOX/.gitkeep",
}
KEY_PREFIXES = tuple("".join(parts) for parts in (("s", "k-"), ("g", "ho_"), ("github", "_pat"), ("AI", "za")))
FORBIDDEN_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]+-----"),
    re.compile(r"(?:" + "|".join(re.escape(prefix) for prefix in KEY_PREFIXES) + r")[A-Za-z0-9_-]{12,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}"),
    re.compile(r"/Users/[^/\\s]+/(?:Desktop|Documents|Library)/"),
)


def verify_installation(profile_path: Path) -> dict[str, Any]:
    manifest = load_manifest(profile_path)
    academic_root = Path(manifest["academic"]["root_directory"]).expanduser()
    install_root = Path(manifest["hermes"]["install_directory"]).expanduser()
    failures: list[str] = []
    checked: list[str] = []
    for relative in sorted(REQUIRED_ROOT_FILES):
        path = academic_root / relative
        checked.append(str(path))
        if not path.is_file():
            failures.append(f"missing required file: {path}")
    for path in sorted(academic_root.rglob("*.md")) if academic_root.exists() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible personal/secret pattern {pattern.pattern!r} in {path}")
    for script in sorted((install_root / "scripts").glob("*.py")) if (install_root / "scripts").exists() else []:
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"script does not compile: {script}: {exc.msg}")
    profile_copy = install_root / "profile.json"
    if not profile_copy.is_file():
        failures.append(f"missing generated profile: {profile_copy}")
    else:
        try:
            copied = json.loads(profile_copy.read_text(encoding="utf-8"))
            if copied != manifest:
                failures.append("generated profile.json differs from the requested manifest")
        except json.JSONDecodeError as exc:
            failures.append(f"generated profile is invalid JSON: {exc}")
    return {
        "status": "pass" if not failures else "fail",
        "academic_root": str(academic_root),
        "install_root": str(install_root),
        "checked_count": len(checked),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="Generated install profile.json")
    args = parser.parse_args()
    result = verify_installation(args.profile.expanduser().resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
