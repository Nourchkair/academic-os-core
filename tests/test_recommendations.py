from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from academia_os.recommendations import RECOMMENDATION_IDS, get_recipe, list_recommendations


ROOT = Path(__file__).parents[1]


def test_recommendation_registry_is_stable_and_machine_readable() -> None:
    registry = list_recommendations()

    assert registry["schema_version"] == 1
    assert registry["ownership"] == {
        "academia": "defines capabilities, recommendations, recipes, and safety boundaries",
        "external_agent": "checks its own tools and implements an approved recipe",
        "student": "authorizes optional access and automations",
    }
    assert tuple(item["id"] for item in registry["workflows"]) == RECOMMENDATION_IDS
    assert len(registry["workflows"]) == 9
    for workflow in registry["workflows"]:
        assert set(("id", "title", "summary", "why_useful", "level", "requires", "optional_capabilities", "student_choices", "suggested_defaults", "setup_steps", "safety_rules", "verification_steps", "maintenance", "academia_interfaces", "adaptation_notes")) <= workflow.keys()
        assert workflow["level"] in {"recommended", "optional", "advanced"}
        assert workflow["requires"]
        assert workflow["safety_rules"]
        assert workflow["verification_steps"]
        assert workflow["academia_interfaces"]
        assert "connected" not in json.dumps(workflow).lower()
        assert "enabled" not in json.dumps(workflow).lower()


def test_recipe_lookup_returns_copy_and_unknown_ids_fail() -> None:
    recipe = get_recipe("daily_academic_brief")
    recipe["title"] = "Changed outside the registry"

    assert get_recipe("daily_academic_brief")["title"] == "Daily Academic Brief"
    with pytest.raises(KeyError, match="unknown recommended workflow"):
        get_recipe("not_a_real_workflow")


def test_daily_brief_and_course_sync_preserve_academia_boundaries() -> None:
    daily = get_recipe("daily_academic_brief")
    sync = get_recipe("course_source_sync")

    assert "academia agent context --scope today --detail compact --json" in daily["academia_interfaces"]
    assert "academia agent attention --json" in daily["academia_interfaces"]
    assert "scheduler_or_automation" in daily["requires"]
    assert daily["suggested_defaults"]["time"] == "09:00"
    assert daily["suggested_defaults"]["timezone"] == "local"
    assert "academia import" in sync["academia_interfaces"]
    safety = " ".join(sync["safety_rules"]).lower()
    assert "submit" in safety
    assert "message" in safety
    assert "cookie" in safety


def test_research_community_practice_and_visual_recipes_declare_authority() -> None:
    research = get_recipe("academic_research_access")
    community = get_recipe("community_research")
    practice = get_recipe("practice_material_discovery")
    visual = get_recipe("visual_learning_sources")

    assert research["authority_notes"]
    assert community["authority_notes"]["authority"] == "non_authoritative_context"
    assert community["authority_notes"]["cannot_establish"]
    assert "academia artifact create" in practice["academia_interfaces"]
    assert "provenance" in " ".join(practice["safety_rules"]).lower()
    assert visual["authority_notes"]["default"] == "supplementary_unless_official"


def test_agent_recommendation_commands_are_read_only_without_a_profile(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    recommendations = subprocess.run(
        [sys.executable, "-m", "academia_os", "agent", "recommendations", "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    recipe = subprocess.run(
        [sys.executable, "-m", "academia_os", "agent", "recipe", "daily_academic_brief", "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert recommendations.returncode == 0, recommendations.stderr
    assert recipe.returncode == 0, recipe.stderr
    assert json.loads(recommendations.stdout)["workflows"]
    assert json.loads(recipe.stdout)["id"] == "daily_academic_brief"
    assert not (tmp_path / ".academia").exists()
    assert not list(tmp_path.iterdir())
