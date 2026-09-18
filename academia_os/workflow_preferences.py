from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import available_timezones

from .recommendations import get_playbook, get_recipe
from .state import JsonStateStore


WORKFLOW_PREFERENCES_SCHEMA_VERSION = 1
WORKFLOW_PREFERENCES_FILENAME = "workflow_preferences.json"

_UNSET = object()
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_UPDATED_BY_PATTERN = re.compile(r"^(?:user|agent:[a-z0-9][a-z0-9._-]{0,63})$")
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "session_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "cookie",
        "cookies",
        "mfa",
        "mfa_code",
        "authorization",
    }
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|token|api[_ -]?key|secret|cookie|mfa(?:[_ -]?code)?|session[_ -]?token|authorization)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{20,}"),
    re.compile(r"\b(?:sk-[a-z0-9]{16,}|gh[pousr]_[a-z0-9]{16,}|AIza[a-z0-9_-]{20,})\b", re.IGNORECASE),
)


def _empty_state() -> dict[str, Any]:
    return {"schema_version": WORKFLOW_PREFERENCES_SCHEMA_VERSION, "workflows": []}


def _normalized_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_")


def _contains_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    parts = set(part for part in normalized.split("_") if part)
    return normalized in _SENSITIVE_KEY_PARTS or bool(parts & _SENSITIVE_KEY_PARTS)


def _validate_text(value: Any, label: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if len(value) > max_length:
        raise ValueError(f"{label} is too long")
    if any(pattern.search(value) for pattern in _SECRET_TEXT_PATTERNS):
        raise ValueError(f"{label} must not contain credentials or secrets")
    return value


def _validate_preference_value(key: str, value: Any, expected: Any) -> Any:
    if _contains_sensitive_key(key):
        raise ValueError("workflow preferences must not contain credential or secret fields")
    if isinstance(expected, bool):
        valid = isinstance(value, bool)
    elif isinstance(expected, str):
        valid = isinstance(value, str)
    elif isinstance(expected, list):
        valid = isinstance(value, list) and all(isinstance(item, type(expected[0])) for item in value) if expected else isinstance(value, list)
    elif expected is None:
        valid = value is None
    else:
        valid = isinstance(value, type(expected)) and not isinstance(value, bool)
    if not valid:
        raise ValueError(f"workflow preference {key!r} must match the playbook's {type(expected).__name__} value type")

    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"workflow preference {key!r} must not be empty")
        if len(value) > 1000:
            raise ValueError(f"workflow preference {key!r} is too long")
        if any(pattern.search(value) for pattern in _SECRET_TEXT_PATTERNS):
            raise ValueError("workflow preferences must not contain credentials or secrets")
        if key == "time" and not _TIME_PATTERN.fullmatch(value):
            raise ValueError("workflow preference time must use HH:MM")
        if key == "detail" and value not in {"compact", "standard", "deep"}:
            raise ValueError("workflow preference detail must be compact, standard, or deep")
        if key == "timezone" and value != "local" and value not in available_timezones():
            raise ValueError("workflow preference timezone must be local or a valid IANA time zone")
    elif isinstance(value, list):
        if len(value) > 64:
            raise ValueError(f"workflow preference {key!r} has too many values")
        for item in value:
            if isinstance(item, str):
                if not item.strip() or len(item) > 500:
                    raise ValueError(f"workflow preference {key!r} contains an invalid text value")
                if any(pattern.search(item) for pattern in _SECRET_TEXT_PATTERNS):
                    raise ValueError("workflow preferences must not contain credentials or secrets")
            elif not isinstance(item, (bool, int, float)) and item is not None:
                raise ValueError(f"workflow preference {key!r} contains an unsupported value")
    return copy.deepcopy(value)


def _validate_preferences(recipe: dict[str, Any], preferences: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(preferences, Mapping):
        raise ValueError("workflow preferences must be a JSON object")
    defaults = recipe["suggested_defaults"]
    for key in preferences:
        if _contains_sensitive_key(str(key)):
            raise ValueError("workflow preferences must not contain credential or secret fields")
    unknown = sorted(str(key) for key in preferences if str(key) not in defaults)
    if unknown:
        raise ValueError(f"unknown workflow preference for {recipe['id']}: {unknown[0]}")
    return {str(key): _validate_preference_value(str(key), value, defaults[str(key)]) for key, value in preferences.items()}


def _validate_updated_by(value: Any) -> str:
    if not isinstance(value, str) or not _UPDATED_BY_PATTERN.fullmatch(value):
        raise ValueError("updated_by must be user or agent:<name>")
    return value


def _validate_saved_record(value: Mapping[str, Any]) -> dict[str, Any]:
    workflow_id = value.get("workflow_id")
    if not isinstance(workflow_id, str):
        raise ValueError("saved workflow preference is missing workflow_id")
    recipe = get_recipe(workflow_id)
    preferences = _validate_preferences(recipe, value.get("preferences", {}))
    custom_instructions = _validate_text(value.get("custom_instructions", ""), "custom_instructions", max_length=5000)
    external_setup_notes = _validate_text(value.get("external_setup_notes", ""), "external_setup_notes", max_length=3000)
    updated_at = value.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ValueError("saved workflow preference is missing updated_at")
    updated_by = _validate_updated_by(value.get("updated_by"))
    return {
        "workflow_id": workflow_id,
        "preferences": preferences,
        "custom_instructions": custom_instructions,
        "external_setup_notes": external_setup_notes,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }


def _validate_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("workflow preference state must be a JSON object")
    if value.get("schema_version") != WORKFLOW_PREFERENCES_SCHEMA_VERSION:
        raise ValueError(f"workflow preference schema_version must be {WORKFLOW_PREFERENCES_SCHEMA_VERSION}")
    workflows = value.get("workflows")
    if not isinstance(workflows, list):
        raise ValueError("workflow preference state workflows must be a list")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in workflows:
        if not isinstance(raw, Mapping):
            raise ValueError("saved workflow preferences must be JSON objects")
        record = _validate_saved_record(raw)
        if record["workflow_id"] in seen:
            raise ValueError(f"duplicate saved workflow preference: {record['workflow_id']}")
        seen.add(record["workflow_id"])
        records.append(record)
    return {"schema_version": WORKFLOW_PREFERENCES_SCHEMA_VERSION, "workflows": records}


def _effective_preferences(recipe: Mapping[str, Any], saved: Mapping[str, Any] | None) -> dict[str, Any]:
    value = copy.deepcopy(dict(recipe["suggested_defaults"]))
    if saved:
        value.update(copy.deepcopy(dict(saved.get("preferences", {}))))
    return value


class WorkflowPreferencesStore:
    """Local student-owned workflow preferences, separate from static playbooks."""

    def __init__(self, academic_root: Path) -> None:
        self.academic_root = Path(academic_root).expanduser().resolve()
        self.path = self.academic_root / ".academia" / WORKFLOW_PREFERENCES_FILENAME
        self.store = JsonStateStore(self.path)

    def _read_state(self) -> dict[str, Any]:
        raw = self.store.read(_empty_state())
        return _validate_state(raw)

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._read_state()["workflows"])

    def get_saved(self, workflow_id: str) -> dict[str, Any] | None:
        recipe = get_recipe(workflow_id)
        del recipe
        return next((copy.deepcopy(item) for item in self._read_state()["workflows"] if item["workflow_id"] == workflow_id), None)

    def show(self, workflow_id: str) -> dict[str, Any]:
        playbook = get_playbook(workflow_id)
        recipe = get_recipe(workflow_id)
        saved = self.get_saved(workflow_id)
        return {
            "workflow_id": workflow_id,
            "recommended_playbook": playbook,
            "recommended_recipe": recipe,
            "saved_preferences": saved,
            "effective_preferences": _effective_preferences(playbook, saved),
            "preference_semantics": "saved preferences describe the student's desired setup; they do not prove external services are connected or automation is running",
        }

    def set(
        self,
        workflow_id: str,
        *,
        preferences: Mapping[str, Any] | None = None,
        custom_instructions: str | None | object = _UNSET,
        external_setup_notes: str | None | object = _UNSET,
        updated_by: str = "user",
    ) -> dict[str, Any]:
        recipe = get_recipe(workflow_id)
        updated_by = _validate_updated_by(updated_by)
        current = self.get_saved(workflow_id)
        current_preferences = dict(current["preferences"]) if current else {}
        if preferences is not None:
            current_preferences.update(_validate_preferences(recipe, preferences))
        validated_preferences = _validate_preferences(recipe, current_preferences)
        if custom_instructions is _UNSET:
            next_custom = current["custom_instructions"] if current else ""
        else:
            next_custom = _validate_text(custom_instructions or "", "custom_instructions", max_length=5000)
        if external_setup_notes is _UNSET:
            next_notes = current["external_setup_notes"] if current else ""
        else:
            next_notes = _validate_text(external_setup_notes or "", "external_setup_notes", max_length=3000)
        record = {
            "workflow_id": workflow_id,
            "preferences": validated_preferences,
            "custom_instructions": next_custom,
            "external_setup_notes": next_notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = _validate_state(raw)
            workflows = [item for item in state["workflows"] if item["workflow_id"] != workflow_id]
            workflows.append(record)
            return {"schema_version": WORKFLOW_PREFERENCES_SCHEMA_VERSION, "workflows": workflows}

        self.store.update(_empty_state(), transition)
        return copy.deepcopy(record)
