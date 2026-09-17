from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from academia_os.semester import resolve_current_semester

SKIP_DIRECTORIES = {".academia", ".git", ".hermes", ".academic-os", "node_modules", "__pycache__", ".venv", "venv"}
OPERATIONAL_DIRECTORIES = {".academia", ".academic-os", ".hermes"}
SKIP_SUFFIXES = {".crdownload", ".part", ".tmp", ".temp"}
SEMESTER_PATTERN = re.compile(r"^(fall|winter|spring|summer)[ _-]*(\d{4})$", re.IGNORECASE)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PLAN_VERSION = 1


@dataclass(frozen=True)
class MigrationItem:
    source: Path
    destination: Path
    relative_path: str
    semester: str
    size: int
    sha256: str

    def as_json(self) -> dict[str, object]:
        value = asdict(self)
        value["source"] = str(self.source)
        value["destination"] = str(self.destination)
        return value


@dataclass(frozen=True)
class MigrationPlan:
    source_root: Path
    academic_root: Path
    current_semester: str
    items: tuple[MigrationItem, ...]
    created_at: str

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    def as_json(self) -> dict[str, object]:
        return {
            "version": PLAN_VERSION,
            "source_root": str(self.source_root),
            "academic_root": str(self.academic_root),
            "current_semester": self.current_semester,
            "created_at": self.created_at,
            "item_count": len(self.items),
            "total_size": self.total_size,
            "items": [item.as_json() for item in self.items],
        }


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _is_strictly_within(path: Path, root: Path) -> bool:
    return path != root and root in path.parents


def _is_operational_path(path: Path) -> bool:
    return any(part.casefold() in OPERATIONAL_DIRECTORIES for part in path.parts)


def _lexical_absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _reject_dot_components(path: Path, label: str) -> None:
    raw_path = os.fsdecode(os.fspath(path))
    expanded_path = os.path.expanduser(raw_path)
    components = expanded_path.split(os.sep)
    if os.altsep:
        components = [part for component in components for part in component.split(os.altsep)]
    if any(part in {".", ".."} for part in components) or any(part in {".", ".."} for part in Path(path).parts):
        raise ValueError(f"migration {label} contains dot path component")


def _validated_absolute_path(path: Path, label: str) -> Path:
    _reject_dot_components(path, label)
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError(f"migration {label} must be absolute")
    return _lexical_absolute_path(path)


def _validated_public_path(path: Path, label: str) -> Path:
    """Make a public path absolute without silently normalizing traversal."""
    _reject_dot_components(path, label)
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return _lexical_absolute_path(path)


def _absolute_plan_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"migration plan {label} must be a non-empty path")
    return _validated_absolute_path(Path(value), f"plan {label}")


def _existing_ancestors(path: Path) -> Iterable[Path]:
    current = path
    while True:
        if os.path.exists(current):
            yield current
        if current.parent == current:
            return
        current = current.parent


def _samefile(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError):
        return False


def _same_physical_path(left: Path, right: Path) -> bool:
    return _samefile(left, right)


def _is_physically_within(path: Path, root: Path, *, strict: bool = False) -> bool:
    """Check lexical containment and, for existing paths, resolved containment."""
    lexical_match = _is_strictly_within(path, root) if strict else _is_within(path, root)
    if lexical_match:
        return True
    if not (os.path.exists(path) and os.path.exists(root)):
        return False
    physical_path = _lexical_absolute_path(Path(os.path.realpath(path)))
    physical_root = _lexical_absolute_path(Path(os.path.realpath(root)))
    return _is_strictly_within(physical_path, physical_root) if strict else _is_within(physical_path, physical_root)


def is_runtime_migration_source(source_root: Path, runtime_root: Path) -> bool:
    """Return whether a selected source is the configured runtime or its child."""
    source_root = _lexical_absolute_path(source_root)
    runtime_root = _lexical_absolute_path(runtime_root)
    return _is_physically_within(source_root, runtime_root)


def validate_migration_source(source_root: Path, runtime_root: Path) -> Path:
    """Reject runtime state before a migration plan can scan or move it."""
    source_root = _lexical_absolute_path(source_root)
    runtime_root = _lexical_absolute_path(runtime_root)
    if is_runtime_migration_source(source_root, runtime_root):
        raise ValueError(f"migration source is the configured runtime directory or a descendant: {runtime_root}")
    return source_root


def _physical_roots_overlap(left: Path, right: Path) -> bool:
    if _is_within(left, right) or _is_within(right, left):
        return True
    if _is_physically_within(left, right) or _is_physically_within(right, left):
        return True
    if _same_physical_path(left, right):
        return True
    if any(_same_physical_path(left, right_ancestor) for right_ancestor in _existing_ancestors(right)):
        return True
    if any(_same_physical_path(left_ancestor, right) for left_ancestor in _existing_ancestors(left)):
        return True
    if os.path.exists(left) and os.path.exists(right):
        left_real = _lexical_absolute_path(Path(os.path.realpath(left)))
        right_real = _lexical_absolute_path(Path(os.path.realpath(right)))
        return _is_within(left_real, right_real) or _is_within(right_real, left_real)
    return False


def _validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("migration plan relative path must be a non-empty string")
    if "\\" in value:
        raise ValueError("migration plan relative path must use safe POSIX separators")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"migration plan relative path contains traversal: {value}")
    relative = Path(value)
    if relative.is_absolute() or not relative.parts:
        raise ValueError(f"migration plan relative path must be relative: {value}")
    return value


def _reject_symlink_components(path: Path, label: str) -> None:
    """Reject symlink path components without resolving the path first."""
    path = _lexical_absolute_path(path)
    for component in (*path.parents, path):
        try:
            if os.path.lexists(component) and os.path.islink(component):
                raise ValueError(f"migration {label} contains symlink component: {component}")
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError(f"cannot inspect migration {label}: {component}") from exc


def _validate_plan_roots(source_root: Path, academic_root: Path, *, prefix: str) -> None:
    if _is_operational_path(source_root):
        raise ValueError(f"{prefix} source root is operational state")
    if _is_operational_path(academic_root):
        raise ValueError(f"{prefix} academic root is operational state")
    if source_root == academic_root or _same_physical_path(source_root, academic_root):
        raise ValueError(f"{prefix} source and academic roots must be different")
    if _physical_roots_overlap(source_root, academic_root):
        raise ValueError(f"{prefix} source and academic roots must be disjoint")
    _reject_symlink_components(source_root, "source root")
    _reject_symlink_components(academic_root, "academic root")
    if not source_root.is_dir():
        raise ValueError(f"{prefix} source root is not a folder: {source_root}")
    if os.path.lexists(academic_root) and not academic_root.is_dir():
        raise ValueError(f"{prefix} academic root is not a folder: {academic_root}")


def _validate_migration_item(item: MigrationItem, source_root: Path, academic_root: Path, index: int) -> MigrationItem:
    if not isinstance(item, MigrationItem):
        raise ValueError(f"migration plan item {index} is malformed")
    if not isinstance(item.source, Path) or not isinstance(item.destination, Path):
        raise ValueError(f"migration plan item {index} paths are malformed")
    relative_path = _validate_relative_path(item.relative_path)
    source = _validated_absolute_path(item.source, f"plan item {index} source")
    destination = _validated_absolute_path(item.destination, f"plan item {index} destination")
    _reject_symlink_components(source, f"item {index} source")
    _reject_symlink_components(destination, f"item {index} destination")
    if not _is_physically_within(source, source_root, strict=True):
        raise ValueError(f"migration plan item {index} source must be a strict descendant of source_root")
    source_relative = source.relative_to(source_root)
    if _is_operational_path(source_relative):
        raise ValueError(f"migration plan item {index} source is operational state")
    if source != _lexical_absolute_path(source_root / relative_path):
        raise ValueError(f"migration plan item {index} source does not match relative path")
    if not _is_physically_within(destination, academic_root, strict=True):
        raise ValueError(f"migration plan item {index} destination must be a strict descendant of academic_root")
    destination_relative = destination.relative_to(academic_root)
    if _is_operational_path(destination_relative):
        raise ValueError(f"migration plan item {index} destination is operational state")
    if not isinstance(item.semester, str) or not SEMESTER_PATTERN.fullmatch(item.semester.strip()):
        raise ValueError(f"migration plan item {index} semester is malformed")
    if type(item.size) is not int or item.size < 0:
        raise ValueError(f"migration plan item {index} size is malformed")
    if not isinstance(item.sha256, str) or not SHA256_PATTERN.fullmatch(item.sha256):
        raise ValueError(f"migration plan item {index} sha256 is malformed")
    return MigrationItem(source, destination, relative_path, item.semester, item.size, item.sha256)


def _validated_plan(plan: MigrationPlan) -> MigrationPlan:
    if not isinstance(plan, MigrationPlan):
        raise ValueError("migration plan is malformed")
    if not isinstance(plan.source_root, Path) or not isinstance(plan.academic_root, Path):
        raise ValueError("migration plan roots are malformed")
    source_root = _validated_absolute_path(plan.source_root, "plan source_root")
    academic_root = _validated_absolute_path(plan.academic_root, "plan academic_root")
    _validate_plan_roots(source_root, academic_root, prefix="migration plan")
    if not isinstance(plan.current_semester, str) or not SEMESTER_PATTERN.fullmatch(plan.current_semester.strip()):
        raise ValueError("migration plan current_semester is malformed")
    if not isinstance(plan.created_at, str) or not plan.created_at.strip():
        raise ValueError("migration plan created_at is malformed")
    try:
        datetime.fromisoformat(plan.created_at)
    except ValueError as exc:
        raise ValueError("migration plan created_at is malformed") from exc
    try:
        plan_items = tuple(plan.items)
    except TypeError as exc:
        raise ValueError("migration plan items must be iterable") from exc
    validated_items = tuple(_validate_migration_item(item, source_root, academic_root, index) for index, item in enumerate(plan_items))
    return MigrationPlan(source_root, academic_root, plan.current_semester, validated_items, plan.created_at)


def validate_migration_plan(plan: MigrationPlan) -> None:
    """Validate all plan boundaries before a caller can perform file operations."""
    _validated_plan(plan)


def ensure_safe_text_target(path: Path) -> None:
    """Reject an existing symlink or directory before a text file is written."""
    path = _validated_public_path(path, "text target")
    _reject_symlink_components(path, "text target")
    if os.path.lexists(path) and path.is_symlink():
        raise ValueError(f"refusing to write through symlink target: {path}")
    if os.path.lexists(path) and path.is_dir():
        raise ValueError(f"refusing to write through directory target: {path}")


def safe_atomic_write_text(path: Path, text: str) -> None:
    """Write text through a same-directory temporary file and atomic replace."""
    path = _validated_public_path(path, "text target")
    _reject_symlink_components(path, "text target")
    ensure_safe_text_target(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        _reject_symlink_components(path, "text target")
        ensure_safe_text_target(path)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_migration_plan(path: Path) -> MigrationPlan:
    """Load and validate a persisted migration plan before any file operation."""
    plan_path = _validated_public_path(path, "plan path")
    _reject_symlink_components(plan_path, "plan path")
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read migration plan {plan_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("migration plan must be a JSON object")

    expected_fields = {"version", "source_root", "academic_root", "current_semester", "created_at", "item_count", "total_size", "items"}
    if "version" not in data or type(data["version"]) is not int or data["version"] != PLAN_VERSION:
        raise ValueError(f"unsupported migration plan version: {data.get('version')!r}")
    if set(data) != expected_fields:
        raise ValueError("migration plan has malformed fields")

    source_root = _absolute_plan_path(data["source_root"], "source_root")
    academic_root = _absolute_plan_path(data["academic_root"], "academic_root")

    current_semester = data["current_semester"]
    if not isinstance(current_semester, str) or not SEMESTER_PATTERN.fullmatch(current_semester.strip()):
        raise ValueError("migration plan current_semester is malformed")
    created_at = data["created_at"]
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("migration plan created_at is malformed")
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError("migration plan created_at is malformed") from exc

    items_data = data["items"]
    if not isinstance(items_data, list):
        raise ValueError("migration plan items must be a list")
    item_count = data["item_count"]
    total_size = data["total_size"]
    if type(item_count) is not int or item_count != len(items_data) or item_count < 0:
        raise ValueError("migration plan item_count is malformed")
    if type(total_size) is not int or total_size < 0:
        raise ValueError("migration plan total_size is malformed")

    items: list[MigrationItem] = []
    for index, item_data in enumerate(items_data):
        if not isinstance(item_data, dict):
            raise ValueError(f"migration plan item {index} is malformed")
        item_fields = {"source", "destination", "relative_path", "semester", "size", "sha256"}
        if set(item_data) != item_fields:
            raise ValueError(f"migration plan item {index} has malformed fields")
        relative_path = _validate_relative_path(item_data["relative_path"])
        source = _absolute_plan_path(item_data["source"], f"item {index} source")
        destination = _absolute_plan_path(item_data["destination"], f"item {index} destination")
        semester = item_data["semester"]
        if not isinstance(semester, str) or not SEMESTER_PATTERN.fullmatch(semester.strip()):
            raise ValueError(f"migration plan item {index} semester is malformed")
        size = item_data["size"]
        if type(size) is not int or size < 0:
            raise ValueError(f"migration plan item {index} size is malformed")
        sha256 = item_data["sha256"]
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise ValueError(f"migration plan item {index} sha256 is malformed")
        items.append(MigrationItem(source, destination, relative_path, semester, size, sha256))

    if total_size != sum(item.size for item in items):
        raise ValueError("migration plan total_size is malformed")
    plan = MigrationPlan(source_root, academic_root, current_semester, tuple(items), created_at)
    return _validated_plan(plan)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_semester(parts: Iterable[str]) -> str | None:
    for part in parts:
        match = SEMESTER_PATTERN.fullmatch(part.strip())
        if match:
            return f"{match.group(1).title()} {match.group(2)}"
    return None


def _markdown_code_span(value: object) -> str:
    """Render an untrusted label as a single-line Markdown code span."""
    text = re.sub(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]", lambda _match: r"\n", str(value))
    longest_backtick_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    delimiter = "`" * (longest_backtick_run + 1)
    return f"{delimiter}{text}{delimiter}"


def _should_skip_file(path: Path) -> bool:
    return path.name in {".DS_Store", "Thumbs.db"} or path.name.startswith("~$") or path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith(".")


def _iter_source_files(source_root: Path, academic_root: Path) -> Iterable[Path]:
    source_root = _lexical_absolute_path(source_root)
    academic_root = _lexical_absolute_path(academic_root)
    for current, directories, files in os.walk(source_root):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if name not in SKIP_DIRECTORIES
            and not name.startswith(".")
            and not (current_path / name).is_symlink()
        ]
        if current_path == academic_root or academic_root in current_path.parents:
            directories[:] = []
            continue
        for filename in files:
            path = current_path / filename
            if not _should_skip_file(path) and not path.is_symlink() and path.is_file():
                yield path


def _destination_for(source_root: Path, academic_root: Path, current_semester: str, source_file: Path) -> tuple[Path, str]:
    relative = source_file.relative_to(source_root)
    semester = detect_semester(relative.parts)
    target_semester = semester or current_semester
    bucket = "00_INBOX" if semester is None or semester == current_semester else "99_ARCHIVE"
    destination = academic_root / target_semester / bucket / "LEGACY_IMPORT" / source_root.name / relative
    return destination, target_semester


def build_migration_plan(source_root: Path, academic_root: Path, current_semester: str) -> MigrationPlan:
    source_root = _validated_public_path(source_root, "source root")
    academic_root = _validated_public_path(academic_root, "academic root")
    _validate_plan_roots(source_root, academic_root, prefix="migration")
    if not isinstance(current_semester, str):
        raise ValueError("current semester is required for migration")
    current_semester = current_semester.strip()
    if current_semester.casefold() in {"current semester", "current"}:
        current_semester = resolve_current_semester()
    if not current_semester:
        raise ValueError("current semester is required for migration")
    items: list[MigrationItem] = []
    for source_file in sorted(_iter_source_files(source_root, academic_root)):
        destination, semester = _destination_for(source_root, academic_root, current_semester, source_file)
        items.append(
            MigrationItem(
                source=source_file,
                destination=destination,
                relative_path=source_file.relative_to(source_root).as_posix(),
                semester=semester,
                size=source_file.stat().st_size,
                sha256=sha256_file(source_file),
            )
        )
    plan = MigrationPlan(source_root, academic_root, current_semester, tuple(items), datetime.now().astimezone().isoformat())
    return _validated_plan(plan)


def _collision_safe_destination(destination: Path) -> Path:
    _reject_symlink_components(destination, "destination")
    if not os.path.lexists(destination):
        return destination
    counter = 1
    while True:
        candidate = destination.with_name(f"{destination.stem} (legacy import {counter}){destination.suffix}")
        _reject_symlink_components(candidate, "destination")
        if not os.path.lexists(candidate):
            return candidate
        counter += 1


def execute_migration_plan(plan: MigrationPlan, *, items: Iterable[MigrationItem] | None = None, mode: str = "copy") -> dict[str, object]:
    if mode not in {"copy", "move"}:
        raise ValueError("migration mode must be copy or move")
    validated_plan = _validated_plan(plan)
    selected_input = list(validated_plan.items if items is None else items)
    for index, item in enumerate(selected_input):
        if not isinstance(item, MigrationItem) or item not in validated_plan.items:
            raise ValueError(f"selected migration item {index} is not part of the migration plan")
    selected = [
        _validate_migration_item(item, validated_plan.source_root, validated_plan.academic_root, index)
        for index, item in enumerate(selected_input)
    ]
    result: dict[str, object] = {"mode": mode, "selected": len(selected), "copied": 0, "moved": 0, "skipped": 0, "failed": 0, "destinations": [], "failures": []}
    destinations = result["destinations"]
    failures = result["failures"]
    assert isinstance(destinations, list)
    assert isinstance(failures, list)
    for index, item in enumerate(selected):
        try:
            safe_item = _validate_migration_item(item, validated_plan.source_root, validated_plan.academic_root, index)
            source = safe_item.source
            if not source.is_file():
                raise FileNotFoundError(f"source is missing: {source}")
            if sha256_file(source) != safe_item.sha256:
                raise ValueError(f"source changed since plan was created: {source}")
            destination = _collision_safe_destination(safe_item.destination)
            _reject_symlink_components(destination, f"item {index} destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(destination, f"item {index} destination")
            shutil.copy2(source, destination)
            if sha256_file(destination) != safe_item.sha256:
                destination.unlink(missing_ok=True)
                raise IOError(f"hash verification failed after copy: {source}")
            destinations.append(str(destination))
            if mode == "move":
                safe_item = _validate_migration_item(safe_item, validated_plan.source_root, validated_plan.academic_root, index)
                source = safe_item.source
                if not source.is_file() or sha256_file(source) != safe_item.sha256:
                    raise ValueError(f"source changed before move: {source}")
                source.unlink()
                result["moved"] = int(result["moved"]) + 1
            else:
                result["copied"] = int(result["copied"]) + 1
        except Exception as exc:
            result["failed"] = int(result["failed"]) + 1
            failures.append(str(exc))
    return result


def _preflight_migration_output_directory(directory: Path) -> None:
    _reject_symlink_components(directory, "migration output directory")
    if not os.path.lexists(directory):
        return
    if directory.is_symlink():
        raise ValueError(f"migration output directory is a symlink: {directory}")
    if not directory.is_dir():
        raise ValueError(f"migration output directory is not a folder: {directory}")


def _preflight_migration_output_target(path: Path, label: str) -> None:
    _reject_symlink_components(path, f"migration {label}")
    if not os.path.lexists(path):
        return
    if path.is_symlink():
        raise ValueError(f"migration {label} is a symlink: {path}")
    if path.is_dir():
        raise ValueError(f"migration {label} is a directory: {path}")
    ensure_safe_text_target(path)


def write_migration_plan(plan: MigrationPlan, directory: Path) -> dict[str, Path]:
    validate_migration_plan(plan)
    directory = _validated_public_path(directory, "migration output directory")
    _preflight_migration_output_directory(directory)
    json_path = directory / "migration-plan.json"
    markdown_path = directory / "MIGRATION_REVIEW.md"
    report_path = directory / "migration-report.json"
    for path, label in (
        (json_path, "plan target"),
        (markdown_path, "review target"),
        (report_path, "report target"),
    ):
        _preflight_migration_output_target(path, label)

    directory.mkdir(parents=True, exist_ok=True)
    _preflight_migration_output_directory(directory)
    for path, label in (
        (json_path, "plan target"),
        (markdown_path, "review target"),
        (report_path, "report target"),
    ):
        _preflight_migration_output_target(path, label)

    safe_atomic_write_text(json_path, json.dumps(plan.as_json(), indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# Legacy material migration review",
        "",
        "This plan was generated from a user-selected folder. Review it before importing.",
        "",
        f"- Source: {_markdown_code_span(plan.source_root)}",
        f"- New Academic OS root: {_markdown_code_span(plan.academic_root)}",
        f"- Current semester: {_markdown_code_span(plan.current_semester)}",
        f"- Files discovered: **{len(plan.items)}**",
        f"- Total bytes: **{plan.total_size}**",
        "",
        "## Safety rules",
        "",
        "- Copy is the default; the legacy source remains intact.",
        "- Move is allowed only after each destination hash matches the source hash.",
        "- Existing destinations are never overwritten; collision copies receive a suffix.",
        "- Semester routing is based only on semester text present in the original path.",
        "- Unknown material is routed to `00_INBOX/LEGACY_IMPORT` for review.",
        "- **Do not move files directly from an AI conversation.** Use the app's explicit confirmation.",
        "",
        "## Proposed items",
        "",
    ]
    for item in plan.items:
        lines.append(
            f"- {_markdown_code_span(item.relative_path)} → "
            f"{_markdown_code_span(item.destination.relative_to(plan.academic_root))} "
            f"({item.size} bytes, {_markdown_code_span(item.sha256[:12] + '…')})"
        )
    if not plan.items:
        lines.append("No eligible files were found.")
    lines.extend(
        [
            "",
            "## AI review prompt",
            "",
            "Review this migration plan and identify likely semester/course groupings using only evidence in file names and contents. Do not invent course identities. Mark uncertain items and propose a destination; do not execute moves. The user must confirm every import.",
        ]
    )
    safe_atomic_write_text(markdown_path, "\n".join(lines) + "\n")

    # A report belongs to the plan that produced it. Only clear it after both
    # replacement outputs have been written successfully.
    _preflight_migration_output_target(report_path, "report target")
    if os.path.lexists(report_path):
        report_path.unlink()
    return {"json": json_path, "markdown": markdown_path}
