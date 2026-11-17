"""Durable intake state under <academic_root>/.academia/knowledge/intake.json."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..state import JsonStateStore
from .model import SCHEMA_VERSION, Candidate, Intake, now


def _default() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "intakes": [], "candidates": []}


class IntakeStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.path = self.workspace_root / ".academia" / "knowledge" / "intake.json"
        self.store = JsonStateStore(self.path)

    def read(self) -> dict[str, Any]:
        value = self.store.read_strict(_default())
        if not isinstance(value, dict):
            raise ValueError("intake state must be an object")
        if not isinstance(value.get("intakes"), list) or not isinstance(value.get("candidates"), list):
            raise ValueError("intake state has an unsupported structure")
        return value

    def list_intakes(self, *, semester: str | None = None) -> list[dict[str, Any]]:
        return [
            dict(item) for item in self.read()["intakes"]
            if isinstance(item, dict) and (semester is None or item.get("semester") == semester)
        ]

    def get_intake(self, intake_id: str) -> dict[str, Any]:
        for item in self.read()["intakes"]:
            if isinstance(item, dict) and item.get("id") == intake_id:
                return dict(item)
        raise KeyError(f"intake not found: {intake_id}")

    def find_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        for item in self.read()["intakes"]:
            if isinstance(item, dict) and item.get("dedupe_key") == dedupe_key:
                return dict(item)
        return None

    def create_intake(self, intake: Intake) -> Intake:
        expected = intake.to_dict()

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _default()
            intakes = [item for item in state.get("intakes", []) if isinstance(item, dict) and item.get("id") != intake.id]
            intakes.append(expected)
            intakes.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
            return {**state, "schema_version": SCHEMA_VERSION, "intakes": intakes}

        self.store.update_strict(_default(), transition)
        return intake

    def update_intake(self, intake_id: str, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        selected: dict[str, Any] = {}

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            nonlocal selected
            state = raw if isinstance(raw, dict) else _default()
            intakes = []
            for item in state.get("intakes", []):
                if not isinstance(item, dict):
                    continue
                if item.get("id") == intake_id:
                    updated = transform(dict(item))
                    updated["updated_at"] = now()
                    intakes.append(updated)
                    selected = dict(updated)
                else:
                    intakes.append(item)
            if not selected:
                raise KeyError(f"intake not found: {intake_id}")
            return {**state, "schema_version": SCHEMA_VERSION, "intakes": intakes}

        self.store.update_strict(_default(), transition)
        return selected

    def add_candidates(self, candidates: list[Candidate]) -> list[Candidate]:
        expected = [candidate.to_dict() for candidate in candidates]
        ids = {candidate.id for candidate in candidates}

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            state = raw if isinstance(raw, dict) else _default()
            values = [item for item in state.get("candidates", []) if isinstance(item, dict) and item.get("id") not in ids]
            values.extend(expected)
            values.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
            return {**state, "schema_version": SCHEMA_VERSION, "candidates": values}

        self.store.update_strict(_default(), transition)
        return candidates

    def list_candidates(self, *, semester: str | None = None, course_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        result = []
        for item in self.read()["candidates"]:
            if not isinstance(item, dict):
                continue
            if semester is not None and item.get("semester") != semester:
                continue
            if course_id is not None and item.get("course_id") != course_id:
                continue
            if status is not None and item.get("status") != status:
                continue
            result.append(dict(item))
        return result

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        for item in self.read()["candidates"]:
            if isinstance(item, dict) and item.get("id") == candidate_id:
                return dict(item)
        raise KeyError(f"intake candidate not found: {candidate_id}")

    def update_candidate(self, candidate_id: str, transform: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        selected: dict[str, Any] = {}

        def transition(raw: dict[str, Any]) -> dict[str, Any]:
            nonlocal selected
            state = raw if isinstance(raw, dict) else _default()
            candidates = []
            for item in state.get("candidates", []):
                if not isinstance(item, dict):
                    continue
                if item.get("id") == candidate_id:
                    updated = transform(dict(item))
                    updated["updated_at"] = now()
                    candidates.append(updated)
                    selected = dict(updated)
                else:
                    candidates.append(item)
            if not selected:
                raise KeyError(f"intake candidate not found: {candidate_id}")
            return {**state, "schema_version": SCHEMA_VERSION, "candidates": candidates}

        self.store.update_strict(_default(), transition)
        return selected
