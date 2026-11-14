from __future__ import annotations

import json
from pathlib import Path

import pytest

from academia_os import review_advice
from academia_os.config import runtime_directory
from academia_os.review import ReviewQueue
from tests.test_agent_interface import prepared_workspace


def queue_for(tmp_path: Path):
    config, root, profile = prepared_workspace(tmp_path)
    queue = ReviewQueue(runtime_directory(config) / "review.json")
    return queue, config, root, profile


def test_advice_filters_invalid_decisions(tmp_path: Path) -> None:
    queue, config, root, profile = queue_for(tmp_path)
    item = queue.add(kind="import_classification", title="Where does lecture8.pptx belong?", details={"name": "lecture8.pptx"})

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(review_advice, "_resolve_model", lambda _profile: (config, {"id": "test", "auth": "bearer"}, "test-model", "key"))
    monkeypatch.setattr(review_advice, "_run_model", lambda record, model, key, prompt: json.dumps({
        "options": [
            {"decision": "choose_course:POL 2103 - Politics", "label": "File under POL 2103", "rationale": "Filename matches."},
            {"decision": "invented_decision", "label": "Nope", "rationale": "Nope."},
            {"decision": "keep_general_intake", "label": "Leave in inbox", "rationale": "Unclear week."},
        ],
        "recommended": "choose_course:POL 2103 - Politics",
        "note": "Check the first slide.",
    }))
    try:
        result = review_advice.advise(item.id, profile=profile)
    finally:
        monkeypatch.undo()

    assert [option["decision"] for option in result["options"]] == [
        "choose_course:POL 2103 - Politics",
        "keep_general_intake",
    ]
    assert result["recommended"] == "choose_course:POL 2103 - Politics"
    assert result["note"] == "Check the first slide."


def test_advice_recommendation_falls_back_to_first_valid_option(tmp_path: Path) -> None:
    queue, config, _, profile = queue_for(tmp_path)
    item = queue.add(kind="deadline_conflict", title="Two due dates", details={"field": "due_date"})

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(review_advice, "_resolve_model", lambda _profile: (config, {"id": "test", "auth": "bearer"}, "test-model", "key"))
    monkeypatch.setattr(review_advice, "_run_model", lambda record, model, key, prompt: json.dumps({
        "options": [
            {"decision": "keep_current", "label": "Keep saved", "rationale": "Matches the syllabus."},
            {"decision": "use_new", "label": "Use new", "rationale": "Matches Brightspace."},
        ],
        "recommended": "not_a_decision",
    }))
    try:
        result = review_advice.advise(item.id, profile=profile)
    finally:
        monkeypatch.undo()

    assert result["recommended"] == "keep_current"
    assert len(result["options"]) == 2


def test_advice_reports_missing_provider(tmp_path: Path) -> None:
    queue, _, _, profile = queue_for(tmp_path)
    item = queue.add(kind="deadline_conflict", title="Two due dates", details={})

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(review_advice, "_resolve_model", lambda _profile: (_ for _ in ()).throw(review_advice.ReviewAdviceError("Connect an API model provider in Settings to use decision help.")))
    try:
        with pytest.raises(review_advice.ReviewAdviceError, match="Connect an API model provider"):
            review_advice.advise(item.id, profile=profile)
    finally:
        monkeypatch.undo()
