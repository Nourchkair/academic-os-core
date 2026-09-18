from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import available_timezones

from academia_os.config import CURRENT_CONFIG_VERSION, hermes_config, migrate_config, runtime_directory, validate_config as validate_canonical_config

SCHEMA_VERSION = CURRENT_CONFIG_VERSION
TEXT_SUFFIXES = {".md", ".json", ".env", ".py", ".sh", ".txt", ".yaml", ".yml"}


def _get(data: dict[str, Any], *keys: str, default: Any = "") -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compatibility facade over the canonical, agent-neutral config validator."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    original_hermes = manifest.get("hermes")
    normalized = validate_canonical_config(migrate_config(manifest) if manifest.get("schema_version") == 1 else manifest)
    # Keep the legacy top-level alias readable for existing callers and old generated profiles.
    if isinstance(original_hermes, dict):
        normalized["hermes"] = original_hermes
    manifest.clear()
    manifest.update(normalized)
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest {path}: {exc}") from exc
    return validate_manifest(manifest)


def profile_tokens(manifest: dict[str, Any]) -> dict[str, str]:
    normalized = migrate_config(manifest) if manifest.get("schema_version") == 1 else manifest
    hermes = hermes_config(normalized)
    legacy_hermes = normalized.get("hermes", {}) if isinstance(normalized.get("hermes"), dict) else {}
    hermes_home = hermes.get("home_directory") or legacy_hermes.get("home_directory", "")
    hermes_profile = hermes.get("profile") or legacy_hermes.get("profile", "default")
    return {
        "STUDENT_NAME": str(_get(normalized, "student", "name")),
        "INSTITUTION": str(_get(normalized, "student", "institution")),
        "PROGRAM": str(_get(normalized, "student", "program")),
        "SEMESTER": str(_get(normalized, "academic", "semester")),
        "TIMEZONE": str(_get(normalized, "academic", "timezone")),
        "ACADEMIC_ROOT": str(Path(str(_get(normalized, "academic", "root_directory"))).expanduser()),
        "INSTALL_ROOT": str(runtime_directory(normalized)),
        "HERMES_HOME": str(Path(str(hermes_home)).expanduser()) if hermes_home else "",
        "HERMES_PROFILE": str(hermes_profile),
        "SCHOOL_PORTAL": str(_get(normalized, "legacy_compatibility", "school_portal_name", default="not configured")),
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


def _iter_copy_sources(source_root: Path) -> list[Path]:
    return [
        source
        for source in sorted(source_root.rglob("*"))
        if "__pycache__" not in source.parts and source.suffix.lower() != ".pyc"
    ]


def _copy_tree(source_root: Path, destination_root: Path, manifest: dict[str, Any], *, allow_existing: bool) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in _iter_copy_sources(source_root):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            _copy_file(source, destination, manifest, allow_existing=allow_existing)


def _ensure_tree(source_root: Path, destination_root: Path, manifest: dict[str, Any]) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in _iter_copy_sources(source_root):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            _copy_file(source, destination, manifest, allow_existing=False)


def _cron_time(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if not match:
        raise ValueError("legacy compatibility automation.daily_brief_time must use HH:MM")
    hour, minute = match.groups()
    return str(int(minute)), str(int(hour))


def build_cron_specs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deprecated neutral jobs only for profiles carrying legacy automation state."""
    validate_manifest(manifest)
    raw_compatibility = manifest.get("legacy_compatibility")
    compatibility = cast(dict[str, Any], raw_compatibility) if isinstance(raw_compatibility, dict) else {}
    raw_automation = compatibility.get("automation")
    automation = cast(dict[str, Any], raw_automation) if isinstance(raw_automation, dict) else None
    if automation is None:
        return []
    academic_root = str(Path(str(_get(manifest, "academic", "root_directory"))).expanduser())
    install_root = runtime_directory(manifest)
    hermes = hermes_config(manifest)
    legacy_hermes = manifest.get("hermes", {}) if isinstance(manifest.get("hermes"), dict) else {}
    profile = str(hermes.get("profile") or legacy_hermes.get("profile", ""))
    specs: list[dict[str, Any]] = []
    if bool(automation.get("daily_brief_enabled", True)):
        minute, hour = _cron_time(str(automation.get("daily_brief_time", "09:00")))
        specs.append(
            {
                "name": "Academic OS — Daily Brief",
                "compatibility": {
                    "deprecated": True,
                    "source": "legacy_compatibility.automation",
                    "execution_owner": "external_agent",
                    "note": "Compatibility only. New installs use the daily_academic_brief Agent Setup Playbook and workflow preferences.",
                },
                "schedule": f"{minute} {hour} * * *",
                "deliver": "local",
                "profile": profile,
                "workdir": academic_root,
                "skills": ["academic-operating-system"],
                "prompt": (
                    "Read the Academia OS rules and current semester/course files under "
                    f"{academic_root}. Produce the daily academic brief using only confirmed "
                    "or explicitly labelled uncertain information. Write the latest generated "
                    "dashboard to the active semester TODAY.md. Do not send messages, submit work, "
                    "or modify Calendar without explicit user confirmation."
                ),
            }
        )
    if bool(automation.get("inbox_processor_enabled", True)):
        interval = int(automation.get("inbox_interval_minutes", 5))
        if interval < 1:
            raise ValueError("legacy compatibility automation.inbox_interval_minutes must be at least 1")
        specs.append(
            {
                "name": "Academic OS — Inbox Processor",
                "compatibility": {
                    "deprecated": True,
                    "source": "legacy_compatibility.automation",
                    "execution_owner": "external_agent",
                    "note": "Compatibility only. New installs do not enable a recurring Academia scheduler.",
                },
                "schedule": f"every {interval}m",
                "deliver": "local",
                "profile": profile,
                "workdir": academic_root,
                "skills": ["academic-operating-system"],
                "script": "academic_os_inbox_gate.py",
                "prompt": (
                    "Process only pending academic inbox records reported by the pre-run gate. "
                    "Preserve originals, classify only when supported, leave uncertain files in place, "
                    "verify successful processing before acknowledging work, and record failures as retryable."
                ),
                "runtime_script": str(install_root / "scripts" / "academic_os_inbox_gate.py"),
            }
        )
    return specs


def _cron_command(spec: dict[str, Any]) -> str:
    """Deprecated compatibility wrapper; Hermes translation lives in adapters.hermes."""
    from adapters.hermes.adapter import HermesAdapter

    config = {"schema_version": CURRENT_CONFIG_VERSION, "agents": {"hermes": {"enabled": True, "profile": spec.get("profile", "default"), "home_directory": ""}}}
    return HermesAdapter(config).cron_command(spec)


def _write_runtime_files(manifest: dict[str, Any], *, repo_root: Path) -> None:
    install_root = runtime_directory(manifest)
    runtime_source = repo_root / "runtime" / "scripts"
    skill_source = repo_root / "runtime" / "skills" / "academic-operating-system"
    core_source = repo_root / "academia_os"
    install_scripts = install_root / "scripts"
    install_skill = install_root / "skill" / "academic-operating-system"
    install_scripts.mkdir(parents=True, exist_ok=True)
    for source in sorted(runtime_source.glob("*.py")):
        if source.name != "academic_os_inbox_gate.py":
            continue
        _copy_file(source, install_scripts / source.name, manifest, allow_existing=False)
    _copy_tree(skill_source, install_skill, manifest, allow_existing=False)
    if core_source.is_dir():
        _copy_tree(core_source, install_root / "academia_os", manifest, allow_existing=False)

    hermes = hermes_config(manifest)
    legacy_hermes = manifest.get("hermes", {}) if isinstance(manifest.get("hermes"), dict) else {}
    hermes_home_value = hermes.get("home_directory") or legacy_hermes.get("home_directory")
    if not hermes.get("enabled") or not hermes_home_value:
        return
    hermes_home = Path(str(hermes_home_value)).expanduser()
    hermes_scripts = hermes_home / "scripts"
    hermes_skill = hermes_home / "skills" / "academic-operating-system"
    adapter_scripts = repo_root / "adapters" / "hermes" / "scripts"
    for source in sorted(adapter_scripts.glob("*.py")):
        _copy_file(source, hermes_scripts / source.name, manifest, allow_existing=False)
    _copy_tree(skill_source, hermes_skill, manifest, allow_existing=False)


# Public compatibility primitive for desktop/adapter callers.
copy_tree_non_destructive = _copy_tree


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
    install_root = runtime_directory(manifest)
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
        f"ACADEMIA_OS_RUNTIME_DIR={shlex.quote(str(install_root))}",
        f"ACADEMIC_OS_INSTALL_DIR={shlex.quote(str(install_root))}",
        f"ACADEMIC_ROOT={shlex.quote(str(academic_root))}",
        f"ACADEMIC_OS_CONFIG={shlex.quote(str(profile_path))}",
        f"ACADEMIC_TIMEZONE={shlex.quote(str(_get(manifest, 'academic', 'timezone')))}",
    ]
    hermes = hermes_config(manifest)
    legacy_hermes = manifest.get("hermes", {}) if isinstance(manifest.get("hermes"), dict) else {}
    hermes_home = hermes.get("home_directory") or legacy_hermes.get("home_directory")
    if hermes_home:
        env_lines.append(f"HERMES_HOME={shlex.quote(str(Path(str(hermes_home)).expanduser()))}")
    env_path = install_root / "academic-os.env"
    if not env_path.exists() or allow_existing:
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    _write_runtime_files(manifest, repo_root=repo_root)
    specs = build_cron_specs(manifest)
    if specs:
        _write_json(install_root / "generated_jobs.json", {"schema_version": 1, "jobs": specs})
        _write_json(install_root / "generated_cron_jobs.json", {"version": 1, "jobs": specs})

    hermes_enabled = bool(hermes.get("enabled") and hermes_home)
    cron_path = install_root / "install_cron.sh"
    if hermes_enabled and specs and (not cron_path.exists() or allow_existing):
        cron_lines = [
            "#!/bin/sh",
            "set -eu",
            f"export HERMES_HOME={shlex.quote(str(Path(str(hermes_home)).expanduser()))}",
            f"export ACADEMIC_OS_INSTALL_DIR={shlex.quote(str(install_root))}",
            f"export ACADEMIC_OS_CONFIG={shlex.quote(str(profile_path))}",
            "# Optional Hermes adapter: review generated_jobs.json before running.",
            "# This script never asks for or handles passwords, API keys, or OAuth tokens.",
        ]
        cron_lines.extend(_cron_command(spec) for spec in specs)
        cron_path.write_text("\n".join(cron_lines) + "\n", encoding="utf-8")
        cron_path.chmod(0o700)

    handoff = install_root / "HANDOFF.md"
    if not handoff.exists() or allow_existing:
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
        "hermes_adapter_enabled": hermes_enabled,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
