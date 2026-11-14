"""Ask the configured model to narrow a Review decision to a few valid options.

The model never decides. It receives the item, the real candidate courses, and
the exact decision ids that Review already accepts, and returns a short list of
options. Anything it invents is dropped before the student sees it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .config import load_config, runtime_directory
from .course_identity import resolve_course_identifier
from .model_connections import ModelConnectionError, ModelConnectionManager
from .review import ReviewQueue, review_decision_ids
from .workspace import build_workspace_snapshot

MAX_OPTIONS = 3
MAX_DETAIL_CHARS = 1200


class ReviewAdviceError(ValueError):
    """Decision help is unavailable or unusable."""


DECISION_LABELS = {
    "keep_current": "Keep the saved value",
    "use_new": "Use the new value",
    "accept_match": "Accept the match",
    "keep_unverified": "Keep it unverified",
    "keep_general_intake": "Leave it in the semester inbox",
    "use_proposed_destination": "Use the proposed destination",
    "keep_unassigned": "Keep it unassigned",
    "approve": "Approve",
    "reject": "Reject",
    "approve_action": "Approve the action",
    "reject_action": "Reject the action",
    "dismiss": "Dismiss",
    "confirm": "Confirm",
}


def _label(decision: str) -> str:
    if decision.startswith("choose_course:"):
        return f"File under {decision.split(':', 1)[1]}"
    return DECISION_LABELS.get(decision, decision.replace("_", " ").title())


def _trim(value: Any, limit: int = MAX_DETAIL_CHARS) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


def _prompt(item: Any, decisions: list[str], courses: list[dict[str, Any]]) -> str:
    course_lines = "\n".join(f"- {course['id']}" for course in courses) or "- (no courses)"
    decision_lines = "\n".join(f"- {decision} → {_label(decision)}" for decision in decisions)
    return (
        "You are helping a student resolve one Review item in a local academic workspace.\n"
        "Return JSON only: {\"options\":[{\"decision\":\"<id>\",\"label\":\"short actionable label\",\"rationale\":\"one or two sentences\"}],\"recommended\":\"<id>\",\"note\":\"optional caveat\"}.\n\n"
        f"Item kind: {item.kind}\nTitle: {item.title}\nCourse: {item.course or '(none)'}\n"
        f"Details: {_trim(item.details)}\n\n"
        f"Allowed decision ids (use only these):\n{decision_lines}\n\n"
        f"Courses available:\n{course_lines}\n\n"
        "Rules: give two or three options, ordered with the best first. Use only allowed decision ids. "
        "Never invent courses, dates, or file paths. If the item genuinely cannot be resolved from the "
        "details, return one option that keeps things unchanged with a note explaining what to check."
    )


def _resolve_model(profile: Path) -> tuple[dict[str, Any], str, str, str]:
    config = load_config(profile)
    manager = ModelConnectionManager(runtime_directory(config) / "model_connections.json")
    state = manager.list()
    for record in state.get("providers", []):
        if not isinstance(record, dict) or record.get("status") != "connected" or not record.get("enabled", True):
            continue
        models = [item for item in record.get("models", []) if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if not models:
            continue
        preferred = state.get("preferences", {}).get("default")
        model = ""
        if isinstance(preferred, str) and preferred.startswith(f"{record['id']}/"):
            candidate = preferred.split("/", 1)[1]
            if any(item["id"] == candidate for item in models):
                model = candidate
        model = model or str(models[0]["id"])
        api_key = manager.credentials.load(str(record["id"])) or ""
        if record.get("auth") != "none" and not api_key:
            continue
        return config, record, model, api_key
    raise ReviewAdviceError("Connect an API model provider in Settings to use decision help.")


def _run_model(record: Mapping[str, Any], model: str, api_key: str, prompt: str) -> str:
    from .assistant.providers.base import ProviderRequest
    from .dashboard_chat import _api_adapter

    adapter = _api_adapter(record, api_key, model)
    response = adapter.complete(ProviderRequest(messages=({"role": "user", "content": prompt},), tools=(), context=""))
    return response.text


def advise(review_id: str, *, profile: Path) -> dict[str, Any]:
    config = load_config(profile)
    state_root = runtime_directory(config)
    item = ReviewQueue(state_root / "review.json").get(review_id)
    snapshot = build_workspace_snapshot(config, persist=False, include_material=False, count_inbox_files=False)
    courses = [
        {"id": str(course.get("id")), "code": course.get("code"), "name": course.get("name")}
        for course in snapshot.get("courses", [])
        if isinstance(course, dict) and course.get("id")
    ]
    decisions = sorted(review_decision_ids(item, courses))
    if not decisions:
        raise ReviewAdviceError("this item has no allowed decisions")
    _, record, model, api_key = _resolve_model(profile)
    raw = _run_model(record, model, api_key, _prompt(item, decisions, courses))
    try:
        value = json.loads(_extract_json(raw))
    except (ValueError, TypeError) as exc:
        raise ReviewAdviceError("the model returned an unusable suggestion; try again") from exc
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in value.get("options", []):
        if not isinstance(entry, dict):
            continue
        decision = entry.get("decision")
        if not isinstance(decision, str) or decision not in decisions or decision in seen:
            continue
        seen.add(decision)
        options.append({
            "decision": decision,
            "label": _trim(entry.get("label"), 120) or _label(decision),
            "rationale": _trim(entry.get("rationale"), 400),
        })
        if len(options) == MAX_OPTIONS:
            break
    if not options:
        raise ReviewAdviceError("the model did not return any valid decision; try again")
    recommended = value.get("recommended") if isinstance(value.get("recommended"), str) else None
    if recommended not in {option["decision"] for option in options}:
        recommended = options[0]["decision"]
    return {
        "review_id": item.id,
        "kind": item.kind,
        "options": options,
        "recommended": recommended,
        "note": _trim(value.get("note"), 400),
        "model": model,
    }


def _extract_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in the response")
    return text[start:end + 1]
