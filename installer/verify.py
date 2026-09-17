#!/usr/bin/env python3
"""Verify Academia OS health separately from safe-to-share privacy audits."""
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

from academia_os.config import load_config, runtime_directory  # noqa: E402

REQUIRED_ROOT_FILES = {
    "README.md", "ACADEMIC_OS_RULES.md", "INTEGRATION_STATUS.md", "VERIFICATION.md", "COURSE_TEMPLATE/README.md",
    "COURSE_TEMPLATE/01_COURSE/README.md", "COURSE_TEMPLATE/00_INBOX/.gitkeep",
}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".env", ".py", ".sh", ".toml", ".csv"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]+-----"),
    "api_key": re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|gho_[A-Za-z0-9_-]{12,}|github_pat_[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,})"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "path": re.compile(r"/Users/[^/\s]+/(?:Desktop|Documents|Library|Downloads)/"),
    "cookie_or_token": re.compile(r"(?i)\b(?:session[_ -]?token|oauth[_ -]?token|refresh[_ -]?token|cookie)\b\s*[:=]"),
}


def verify_installation(profile_path: Path) -> dict[str, Any]:
    config = load_config(profile_path)
    academic_root = Path(config["academic"]["root_directory"]).expanduser().resolve()
    install_root = runtime_directory(config)
    failures: list[str] = []
    checked: list[str] = []
    for relative in sorted(REQUIRED_ROOT_FILES):
        path = academic_root / relative
        checked.append(str(path))
        if not path.is_file():
            failures.append(f"missing required file: {path}")
    required_runtime = [install_root / "profile.json", install_root / "generated_jobs.json", install_root / "scripts" / "academic_os_inbox_gate.py", install_root / "academia_os" / "__init__.py"]
    for path in required_runtime:
        checked.append(str(path))
        if not path.is_file():
            failures.append(f"missing runtime file: {path}")
    for script in sorted((install_root / "scripts").glob("*.py")) if (install_root / "scripts").exists() else []:
        try:
            py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"script does not compile: {script}: {exc.msg}")
    for source in sorted((install_root / "academia_os").rglob("*.py")) if (install_root / "academia_os").exists() else []:
        try:
            py_compile.compile(str(source), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"core module does not compile: {source}: {exc.msg}")
    profile_copy = install_root / "profile.json"
    if profile_copy.is_file():
        try:
            copied = load_config(profile_copy)
            if copied != config:
                failures.append("generated profile.json differs from the requested configuration")
        except (OSError, ValueError) as exc:
            failures.append(f"generated profile is invalid: {exc}")
    return {
        "status": "pass" if not failures else "fail",
        "academic_root": str(academic_root),
        "install_root": str(install_root),
        "checked_count": len(checked),
        "failures": failures,
        "scope": "system_health",
    }


def safe_to_share_audit(folder: Path) -> dict[str, Any]:
    folder = Path(folder).expanduser().resolve()
    findings: list[dict[str, str]] = []
    if not folder.is_dir():
        return {"status": "error", "folder": str(folder), "findings": [{"kind": "missing_folder", "path": str(folder)}]}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"kind": kind, "path": str(path)})
    return {"status": "pass" if not findings else "review", "folder": str(folder), "findings": findings, "scope": "safe_to_share"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="Generated install profile.json")
    parser.add_argument("--share-audit", type=Path, help="Audit a folder before sharing/exporting")
    args = parser.parse_args()
    result = safe_to_share_audit(args.share_audit) if args.share_audit else verify_installation(args.profile.expanduser().resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"pass", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
