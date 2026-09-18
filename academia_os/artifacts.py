from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .activity import ActivityLog
from .course_identity import resolve_course_directory, source_course_id
from .domain import DomainProjection
from .provenance import ProvenanceLabel
from .state import JsonStateStore

ARTIFACT_SCHEMA_VERSION = 1
ARTIFACT_KINDS = (
    "study_guide",
    "reading_summary",
    "practice_questions",
    "study_plan",
    "exam_review",
    "class_notes",
    "source_notes",
    "assignment_outline",
    "working_draft",
    "other",
)
SOURCE_DERIVED_KINDS = frozenset({"study_guide", "reading_summary", "practice_questions", "exam_review", "source_notes", "assignment_outline"})
MAX_ARTIFACT_CONTENT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class GeneratedArtifact:
    id: str
    course_id: str
    kind: str
    title: str
    path: str
    provenance: str
    created_at: str
    updated_at: str
    created_by: str | None
    source_refs: tuple[dict[str, Any], ...]
    domain_refs: tuple[dict[str, Any], ...]
    authoritative: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeneratedArtifact":
        return cls(
            id=str(value["id"]),
            course_id=str(value["course_id"]),
            kind=str(value["kind"]),
            title=str(value["title"]),
            path=str(value["path"]),
            provenance=str(value.get("provenance", ProvenanceLabel.AI_GENERATED.value)),
            created_at=str(value["created_at"]),
            updated_at=str(value.get("updated_at", value["created_at"])),
            created_by=value.get("created_by"),
            source_refs=tuple(value.get("source_refs", ())),
            domain_refs=tuple(value.get("domain_refs", ())),
            authoritative=bool(value.get("authoritative", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_refs"] = list(self.source_refs)
        value["domain_refs"] = list(self.domain_refs)
        return value


class ArtifactStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.store = JsonStateStore(self.path)

    def list(self) -> list[dict[str, Any]]:
        value = self.store.read({"schema_version": ARTIFACT_SCHEMA_VERSION, "artifacts": []})
        if isinstance(value, dict):
            raw = value.get("artifacts", [])
        else:
            raw = value
        if not isinstance(raw, list):
            return []
        workspace_root = self.path.parent.parent.resolve()
        valid: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if item.get("provenance") != ProvenanceLabel.AI_GENERATED.value or item.get("authoritative") is not False:
                continue
            try:
                raw_path = Path(str(item["path"])).expanduser()
                if raw_path.is_symlink():
                    continue
                _reject_symlink_components(raw_path, workspace_root, "registered artifact")
                relative = raw_path.resolve().relative_to(workspace_root)
            except (OSError, ValueError, KeyError):
                continue
            if ".academia" in relative.parts or not relative.parts:
                continue
            try:
                valid.append(GeneratedArtifact.from_dict(item).as_dict())
            except (KeyError, TypeError, ValueError):
                continue
        return valid

    def add(self, artifact: GeneratedArtifact) -> dict[str, Any]:
        value = artifact.as_dict()

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": ARTIFACT_SCHEMA_VERSION, "artifacts": []}
            artifacts = [item for item in state.get("artifacts", []) if isinstance(item, dict) and item.get("id") != artifact.id]
            artifacts.append(value)
            state["schema_version"] = ARTIFACT_SCHEMA_VERSION
            state["artifacts"] = artifacts
            return state

        self.store.update({"schema_version": ARTIFACT_SCHEMA_VERSION, "artifacts": []}, transition)
        return value

    def get(self, artifact_id: str) -> dict[str, Any]:
        for artifact in self.list():
            if artifact["id"] == artifact_id:
                return artifact
        raise KeyError(f"generated artifact not found: {artifact_id}")

    def remove(self, artifact_id: str) -> None:
        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else {"schema_version": ARTIFACT_SCHEMA_VERSION, "artifacts": []}
            state["artifacts"] = [item for item in state.get("artifacts", []) if not isinstance(item, dict) or item.get("id") != artifact_id]
            state["schema_version"] = ARTIFACT_SCHEMA_VERSION
            return state

        if self.path.is_file():
            self.store.update({"schema_version": ARTIFACT_SCHEMA_VERSION, "artifacts": []}, transition)


def artifact_index(workspace_root: Path) -> dict[str, dict[str, Any]]:
    root = Path(workspace_root).expanduser().resolve()
    artifact_path = root / ".academia" / "artifacts.json"
    if not artifact_path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for artifact in ArtifactStore(artifact_path).list():
        try:
            relative = Path(artifact["path"]).expanduser().resolve().relative_to(root)
            resolved = root / relative
        except (OSError, ValueError, KeyError):
            continue
        if ".academia" in relative.parts or not relative.parts or not resolved.is_file() or resolved.is_symlink():
            continue
        result[relative.as_posix()] = artifact
    return result


def _reject_symlink_components(path: Path, root: Path, label: str) -> None:
    lexical = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    root = Path(root).expanduser().resolve()
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact {label} must remain inside the academic workspace") from exc
    current = root
    for component in relative.parts:
        current = current / component
        if os.path.lexists(current) and os.path.islink(current):
            raise ValueError(f"artifact {label} contains a symlink component: {current}")


def _course_root(workspace_root: Path, semester: str, course_id: str) -> Path:
    course_root = resolve_course_directory(workspace_root, semester, course_id)
    _reject_symlink_components(course_root, workspace_root, "course")
    return course_root


def _safe_source_reference(workspace_root: Path, reference: str) -> dict[str, Any]:
    if not isinstance(reference, str) or not reference.strip() or "\x00" in reference:
        raise ValueError("source references must be non-empty strings without NUL bytes")
    raw = reference.strip()
    root = workspace_root.resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        _reject_symlink_components(candidate, root, "source reference")
    except ValueError as exc:
        raise ValueError("source reference must identify recognized academic material") from exc
    if candidate.is_symlink():
        raise ValueError("source references cannot be symlinks")
    try:
        resolved = candidate.resolve()
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("source reference must identify recognized academic material") from exc
    if ".academia" in relative.parts or not resolved.is_file():
        raise ValueError("source references must identify regular academic workspace files, not operational state")
    actual_course_id = source_course_id(root, resolved)
    return {
        "type": "file",
        "id": relative.as_posix(),
        "relative_path": relative.as_posix(),
        "course_id": actual_course_id,
        "exists": True,
    }


def _domain_reference(projection: DomainProjection, course_id: str, reference: str) -> dict[str, Any]:
    matches = [entity for entity in projection.list() if entity.get("id") == reference and entity.get("course_id") == course_id]
    if not matches:
        raise KeyError(f"domain reference not found for course: {reference}")
    entity = matches[0]
    return {"type": "domain", "id": str(entity["id"]), "entity_type": entity.get("entity_type"), "course_id": course_id, "title": entity.get("title")}


def _normalize_kind(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("artifact kind is required")
    normalized = re.sub(r"[^a-z0-9_-]+", "_", value.strip().casefold()).strip("_-")
    if not normalized or len(normalized) > 64:
        raise ValueError("artifact kind must be a short identifier")
    return normalized


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return (slug[:80] or "artifact")


def _validate_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip() or "\x00" in title:
        raise ValueError("artifact title is required")
    if any(ord(character) < 32 for character in title) or len(title.strip()) > 200:
        raise ValueError("artifact title must be printable and at most 200 characters")
    return title.strip()


def _markdown_label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("\r", " ").replace("\n", " ")


def _validate_created_by(created_by: str | None) -> str | None:
    if created_by is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", created_by.strip()):
        raise ValueError("created_by must contain only letters, numbers, '.', '_', ':', or '-'")
    return created_by.strip()


def _collision_safe_write(directory: Path, title: str, content: str, *, workspace_root: Path) -> Path:
    _reject_symlink_components(directory, workspace_root, "generated destination")
    directory.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(directory, workspace_root, "generated destination")
    stem = _slug(title)
    for counter in range(1, 10_000):
        suffix = "" if counter == 1 else f" ({counter})"
        destination = directory / f"{stem}{suffix}.md"
        try:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        return destination
    raise OSError("could not choose a collision-safe generated artifact filename")


def create_generated_artifact(
    workspace_root: Path,
    *,
    semester: str,
    course_id: str,
    kind: str,
    title: str,
    content: str,
    source_refs: Iterable[str] = (),
    domain_refs: Iterable[str] = (),
    created_by: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not isinstance(content, str):
        raise ValueError("artifact content must be text")
    if len(content.encode("utf-8")) > MAX_ARTIFACT_CONTENT_BYTES:
        raise ValueError("artifact content is too large")
    course_root = _course_root(root, semester, course_id)
    normalized_course_id = course_root.name
    normalized_kind = _normalize_kind(kind)
    normalized_title = _validate_title(title)
    normalized_creator = _validate_created_by(created_by)
    projection = DomainProjection(root / ".academia" / "domain.json")
    sources = tuple(_safe_source_reference(root, value) for value in source_refs)
    domains = tuple(_domain_reference(projection, normalized_course_id, value) for value in domain_refs)
    if normalized_kind in SOURCE_DERIVED_KINDS and not sources and not domains:
        raise ValueError(f"artifact kind {normalized_kind} requires at least one source or domain reference")
    created_at = datetime.now(timezone.utc).isoformat()
    source_lines = [f"- `{_markdown_label(item.get('relative_path', item.get('id')))}`" for item in sources]
    domain_lines = [f"- `{_markdown_label(item['entity_type'])}:{_markdown_label(item['id'])}` — {_markdown_label(item.get('title') or 'domain reference')}" for item in domains]
    creator_line = _markdown_label(normalized_creator or "unknown agent")
    header = [
        f"# {_markdown_label(normalized_title)}",
        "",
        "> **Provenance:** AI-GENERATED",
        "> **Authoritative:** false",
        f"> **Created by:** {creator_line}",
        f"> **Created at:** {created_at}",
        "",
    ]
    if source_lines:
        header.extend(["## Sources", *source_lines, ""])
    if domain_lines:
        header.extend(["## Domain references", *domain_lines, ""])
    header.extend(["---", "", content.rstrip(), ""])
    destination = _collision_safe_write(course_root / "06_KNOWLEDGE" / "AI_GENERATED", normalized_title, "\n".join(header), workspace_root=root)
    artifact = GeneratedArtifact(
        id=str(uuid4()),
        course_id=normalized_course_id,
        kind=normalized_kind,
        title=normalized_title,
        path=str(destination),
        provenance=ProvenanceLabel.AI_GENERATED.value,
        created_at=created_at,
        updated_at=created_at,
        created_by=normalized_creator,
        source_refs=sources,
        domain_refs=domains,
        authoritative=False,
    )
    store = ArtifactStore(root / ".academia" / "artifacts.json")
    try:
        value = store.add(artifact)
        ActivityLog(root / ".academia" / "activity.jsonl").append(
            event_type="artifact.created",
            title=f"Created AI-generated material: {normalized_title}",
            course=normalized_course_id,
            details={"artifact_id": artifact.id, "kind": normalized_kind, "path": str(destination), "source_refs": list(sources), "domain_refs": list(domains), "provenance": artifact.provenance, "authoritative": False},
            source=str(destination),
            confidence="secondary-material",
            actor=f"agent:{normalized_creator or 'unknown'}",
        )
    except Exception:
        try:
            store.remove(artifact.id)
        except Exception:
            pass
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return value
