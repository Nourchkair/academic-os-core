from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

SCHEMA_VERSION = 1
TEXT_SUFFIXES = {".md", ".json", ".env", ".py", ".sh", ".txt", ".yaml", ".yml"}


def _get(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    required = {
        "student.name": _get(manifest, "student", "name"),
        "student.institution": _get(manifest, "student", "institution"),
        "academic.semester": _get(manifest, "academic", "semester"),
        "academic.timezone": _get(manifest, "academic", "timezone"),
        "academic.root_directory": _get(manifest, "academic", "root_directory"),
        "hermes.home_directory": _get(manifest, "hermes", "home_directory"),
        "hermes.install_directory": _get(manifest, "hermes", "install_directory"),
    }
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
    if str(required["academic.timezone"]) not in available_timezones():
        raise ValueError("academic.timezone must be a valid IANA time zone; choose a region from the setup list")
    root = Path(str(required["academic.root_directory"])).expanduser()
    install = Path(str(required["hermes.install_directory"])).expanduser()
    hermes = Path(str(required["hermes.home_directory"])).expanduser()
    if root == Path("/") or install == Path("/") or hermes == Path("/"):
        raise ValueError("root, install, and Hermes directories cannot be filesystem root")
    manifest.setdefault("student", {}).setdefault("program", "")
    manifest.setdefault("preferences", {})
    manifest.setdefault("integrations", {})
    manifest.setdefault("automation", {})
    manifest.setdefault("browser", {})
    manifest.setdefault("hermes", {}).setdefault("profile", "default")
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest {path}: {exc}") from exc
    return validate_manifest(manifest)


def profile_tokens(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        "STUDENT_NAME": str(_get(manifest, "student", "name")),
        "INSTITUTION": str(_get(manifest, "student", "institution")),
        "PROGRAM": str(_get(manifest, "student", "program")),
        "SEMESTER": str(_get(manifest, "academic", "semester")),
        "TIMEZONE": str(_get(manifest, "academic", "timezone")),
        "ACADEMIC_ROOT": str(Path(str(_get(manifest, "academic", "root_directory"))).expanduser()),
        "INSTALL_ROOT": str(Path(str(_get(manifest, "hermes", "install_directory"))).expanduser()),
        "HERMES_HOME": str(Path(str(_get(manifest, "hermes", "home_directory"))).expanduser()),
        "HERMES_PROFILE": str(_get(manifest, "hermes", "profile", default="default")),
        "SCHOOL_PORTAL": str(_get(manifest, "academic", "school_portal", default="configured school portal")),
    }


def render_text(text: str, manifest: dict[str, Any]) -> str:
    rendered = text
    for key, value in profile_tokens(manifest).items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _same_content(source: Path, destination: Path) -> bool:
    if not destination.is_file() or source.stat().st_size != destination.stat().st_size:
        return False
    return source.read_bytes() == destination.read_bytes()


def _copy_file(source: Path, destination: Path, manifest: dict[str, Any], *, allow_existing: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _same_content(source, destination):
            return
        if not allow_existing:
            raise FileExistsError(f"refusing to overwrite existing file: {destination}")
        raise FileExistsError(f"existing file differs; manual review required: {destination}")
    if source.suffix.lower() in TEXT_SUFFIXES:
        destination.write_text(render_text(source.read_text(encoding="utf-8"), manifest), encoding="utf-8")
    else:
        shutil.copy2(source, destination)


def _copy_tree(source_root: Path, destination_root: Path, manifest: dict[str, Any], *, allow_existing: bool) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            _copy_file(source, destination, manifest, allow_existing=allow_existing)


def _ensure_tree(source_root: Path, destination_root: Path, manifest: dict[str, Any]) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            _copy_file(source, destination, manifest, allow_existing=False)


def _cron_time(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if not match:
        raise ValueError("automation.daily_brief_time must use HH:MM")
    hour, minute = match.groups()
    return str(int(minute)), str(int(hour))


def build_cron_specs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    validate_manifest(manifest)
    academic_root = str(Path(str(_get(manifest, "academic", "root_directory"))).expanduser())
    install_root = Path(str(_get(manifest, "hermes", "install_directory"))).expanduser()
    hermes_home = Path(str(_get(manifest, "hermes", "home_directory"))).expanduser()
    profile = str(_get(manifest, "hermes", "profile", default="default"))
    specs: list[dict[str, Any]] = []
    automation = manifest.get("automation", {})
    if bool(automation.get("daily_brief_enabled", True)):
        minute, hour = _cron_time(str(automation.get("daily_brief_time", "09:00")))
        specs.append(
            {
                "name": "Academic OS — Daily Brief",
                "schedule": f"{minute} {hour} * * *",
                "deliver": "local",
                "profile": profile,
                "workdir": academic_root,
                "skills": ["academic-operating-system"],
                "prompt": (
                    "Read the Academic OS rules and current semester/course files under "
                    f"{academic_root}. Produce the daily academic brief using only confirmed "
                    "or explicitly labelled uncertain information. Consider deadlines, workload, "
                    "assessment weight, dependencies, weak areas, progress, Calendar/Gmail when "
                    "authorized, and configured study preferences. Write the latest generated "
                    "dashboard to the active semester TODAY.md. Do not send email or modify Calendar "
                    "without explicit user confirmation."
                ),
            }
        )
    if bool(automation.get("inbox_processor_enabled", True)):
        interval = int(automation.get("inbox_interval_minutes", 5))
        if interval < 1:
            raise ValueError("automation.inbox_interval_minutes must be at least 1")
        gate = hermes_home / "scripts" / "academic_os_inbox_gate.py"
        specs.append(
            {
                "name": "Academic OS — Inbox Processor",
                "schedule": f"every {interval}m",
                "deliver": "local",
                "profile": profile,
                "workdir": academic_root,
                "skills": ["academic-operating-system"],
                "script": gate.name,
                "prompt": (
                    "Process only the changed academic inbox files reported by the pre-run gate. "
                    "Follow the Academic OS inbox protocol: inspect content, preserve originals, "
                    "classify only when supported, leave uncertain files in place with an uncertainty "
                    "note, update dependent files only when evidence supports it, and verify side effects."
                ),
            }
        )
    return specs


def _cron_command(spec: dict[str, Any]) -> str:
    args = ["hermes", "cron", "create", str(spec["schedule"]), str(spec["prompt"])]
    args.extend(["--name", str(spec["name"]), "--deliver", "local", "--workdir", str(spec["workdir"])])
    if spec.get("profile"):
        args.extend(["--profile", str(spec["profile"])])
    for skill in spec.get("skills", []):
        args.extend(["--skill", str(skill)])
    if spec.get("script"):
        args.extend(["--script", str(spec["script"])])
    return " ".join(shlex.quote(arg) for arg in args)


def _write_runtime_files(manifest: dict[str, Any], *, repo_root: Path) -> None:
    install_root = Path(str(_get(manifest, "hermes", "install_directory"))).expanduser()
    hermes_home = Path(str(_get(manifest, "hermes", "home_directory"))).expanduser()
    runtime_source = repo_root / "runtime" / "scripts"
    skill_source = repo_root / "runtime" / "skills" / "academic-operating-system"
    install_scripts = install_root / "scripts"
    install_scripts.mkdir(parents=True, exist_ok=True)
    hermes_scripts = hermes_home / "scripts"
    hermes_skill = hermes_home / "skills" / "academic-operating-system"
    for source in sorted(runtime_source.glob("*.py")):
        _copy_file(source, install_scripts / source.name, manifest, allow_existing=False)
        _copy_file(source, hermes_scripts / source.name, manifest, allow_existing=False)
    for source in sorted(skill_source.rglob("*")):
        destination_relative = source.relative_to(skill_source)
        if source.is_dir():
            (install_root / "skill" / destination_relative).mkdir(parents=True, exist_ok=True)
            (hermes_skill / destination_relative).mkdir(parents=True, exist_ok=True)
        else:
            _copy_file(source, install_root / "skill" / destination_relative, manifest, allow_existing=False)
            _copy_file(source, hermes_skill / destination_relative, manifest, allow_existing=False)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def initialize_installation(
    manifest: dict[str, Any],
    *,
    template_root: Path,
    repo_root: Path,
    allow_existing: bool = False,
    attach_existing: bool = False,
) -> dict[str, Any]:
    validate_manifest(manifest)
    academic_root = Path(str(_get(manifest, "academic", "root_directory"))).expanduser()
    install_root = Path(str(_get(manifest, "hermes", "install_directory"))).expanduser()
    root_exists_with_content = academic_root.exists() and any(academic_root.iterdir())
    if root_exists_with_content and not allow_existing and not attach_existing:
        raise FileExistsError(f"academic root is not empty; refusing to modify it: {academic_root}")
    academic_root.mkdir(parents=True, exist_ok=True)
    if attach_existing:
        if not (academic_root / "ACADEMIC_OS_RULES.md").is_file() or not (academic_root / "COURSE_TEMPLATE").is_dir():
            raise ValueError("selected folder does not look like an existing Academic OS folder")
        _ensure_tree(template_root, academic_root, manifest)
    else:
        _copy_tree(template_root, academic_root, manifest, allow_existing=allow_existing)

    semester = str(_get(manifest, "academic", "semester"))
    semester_root = academic_root / semester
    semester_template = template_root / "SEMESTER_TEMPLATE"
    if attach_existing:
        _ensure_tree(semester_template, semester_root, manifest)
    else:
        _copy_tree(semester_template, semester_root, manifest, allow_existing=allow_existing)

    install_root.mkdir(parents=True, exist_ok=True)
    profile_path = install_root / "profile.json"
    if profile_path.exists():
        existing_profile = load_manifest(profile_path)
        if existing_profile != manifest:
            raise FileExistsError(f"existing install profile differs; manual review required: {profile_path}")
    else:
        _write_json(profile_path, manifest)
    env_lines = [
        f"ACADEMIC_OS_INSTALL_DIR={shlex.quote(str(install_root))}",
        f"ACADEMIC_ROOT={shlex.quote(str(academic_root))}",
        f"HERMES_HOME={shlex.quote(str(Path(str(_get(manifest, 'hermes', 'home_directory'))).expanduser()))}",
        f"ACADEMIC_OS_CONFIG={shlex.quote(str(install_root / 'profile.json'))}",
        f"ACADEMIC_TIMEZONE={shlex.quote(str(_get(manifest, 'academic', 'timezone')))}",
    ]
    (install_root / "academic-os.env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    _write_runtime_files(manifest, repo_root=repo_root)
    specs = build_cron_specs(manifest)
    _write_json(install_root / "generated_cron_jobs.json", {"version": 1, "jobs": specs})
    cron_lines = [
        "#!/bin/sh",
        "set -eu",
        f"export HERMES_HOME={shlex.quote(str(Path(str(_get(manifest, 'hermes', 'home_directory'))).expanduser()))}",
        f"export ACADEMIC_OS_INSTALL_DIR={shlex.quote(str(install_root))}",
        f"export ACADEMIC_OS_CONFIG={shlex.quote(str(install_root / 'profile.json'))}",
        "# Review generated_cron_jobs.json before running. These jobs deliver locally only.",
        "# This script never asks for or handles passwords, API keys, or OAuth tokens.",
    ]
    cron_lines.extend(_cron_command(spec) for spec in specs)
    (install_root / "install_cron.sh").write_text("\n".join(cron_lines) + "\n", encoding="utf-8")
    (install_root / "install_cron.sh").chmod(0o700)
    handoff = install_root / "HANDOFF.md"
    handoff.write_text(
        render_text(
            (repo_root / "docs" / "local-installation-handoff.md").read_text(encoding="utf-8"),
            manifest,
        ),
        encoding="utf-8",
    )
    return {
        "status": "initialized",
        "academic_root": str(academic_root),
        "install_root": str(install_root),
        "semester_root": str(semester_root),
        "cron_job_count": len(specs),
        "generated_at": datetime.now().astimezone().isoformat(),
    }
