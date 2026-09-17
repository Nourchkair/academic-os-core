from __future__ import annotations

import json
from pathlib import Path

from academia_os.config import CURRENT_CONFIG_VERSION, SEMESTER_PATTERN, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_schema_conforms_to_canonical_config_contract() -> None:
    schema = json.loads((ROOT / "config" / "manifest.schema.json").read_text(encoding="utf-8"))
    example_path = ROOT / "config" / "manifest.example.json"
    example = load_config(example_path)
    assert schema["properties"]["schema_version"]["const"] == CURRENT_CONFIG_VERSION
    assert set(schema["required"]) >= {"schema_version", "student", "academic", "runtime", "automation", "acquisition", "privacy", "browser", "agents"}
    assert schema["properties"]["academic"]["properties"]["semester"]["pattern"] == SEMESTER_PATTERN.pattern
    assert example["schema_version"] == CURRENT_CONFIG_VERSION
    assert example["academic"]["semester"] != "Current Semester"
