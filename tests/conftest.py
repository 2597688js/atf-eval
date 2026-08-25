"""Shared fixtures: paths into agent-eval-main (the canonical spec/schema
repo) and a loaded JSON Schema validator for the normalized trajectory
contract."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_EVAL_MAIN = REPO_ROOT / "agent-eval-main"


@pytest.fixture(scope="session")
def canonical_schema() -> dict:
    schema_path = AGENT_EVAL_MAIN / "schema" / "normalized_trajectory.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def canonical_validator(canonical_schema: dict) -> jsonschema.Validator:
    return jsonschema.Draft202012Validator(canonical_schema)
