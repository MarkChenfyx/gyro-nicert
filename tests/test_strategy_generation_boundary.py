from __future__ import annotations

import json
from pathlib import Path

from strategy_generation import generate_strategy_from_text
from tests.test_api_strategy_generator import VALID_CODE, patch_provider


REQUIRED_KEYS = {
    "success",
    "source_text",
    "strategy_name",
    "class_name",
    "strategy_code",
    "params",
    "spec",
    "diagnostics",
    "generator_name",
    "generator_version",
    "error",
}


def test_generate_strategy_from_text_returns_stable_success_contract(monkeypatch) -> None:
    code_json = json.dumps(VALID_CODE)
    patch_provider(
        monkeypatch,
        f"""{{
  "success": true,
  "strategy_name": "MA Breakout",
  "class_name": "ApiMaStrategy",
  "strategy_code": {code_json},
  "parameters": {{"fixed_size": {{"default": 1, "description": "fixed order size"}}}},
  "description": "test strategy",
  "strategy_type": "trend_following",
  "diagnostics": [],
  "error": null
}}""",
    )
    result = generate_strategy_from_text("moving average breakout strategy")

    assert set(result) == REQUIRED_KEYS
    assert result["success"] is True
    assert result["source_text"] == "moving average breakout strategy"
    assert result["strategy_name"] == "MA Breakout"
    assert result["class_name"]
    assert "class " in result["strategy_code"]
    assert result["params"]["fixed_size"] == 1
    assert result["spec"]["strategy_type"] == "trend_following"
    assert result["diagnostics"]
    assert result["generator_name"] == "api_strategy_generator"
    assert result["generator_version"]
    assert result["error"] is None


def test_generate_strategy_from_text_failure_contract(monkeypatch) -> None:
    result = generate_strategy_from_text("   ")

    assert set(result) == REQUIRED_KEYS
    assert result["success"] is False
    assert result["strategy_code"] is None
    assert result["error"] == "source_text is empty"
    assert result["diagnostics"][0]["level"] == "error"


def test_generate_strategy_from_text_uses_api_generator(monkeypatch) -> None:
    code_json = json.dumps(VALID_CODE)
    patch_provider(
        monkeypatch,
        f"""{{
  "success": true,
  "strategy_name": "API MA Strategy",
  "class_name": "ApiMaStrategy",
  "strategy_code": {code_json},
  "parameters": {{"fixed_size": {{"default": 1, "description": "fixed order size"}}}},
  "description": "test strategy",
  "strategy_type": "trend_following",
  "diagnostics": [],
  "error": null
}}""",
    )

    result = generate_strategy_from_text("use moving averages")

    assert result["success"] is True
    assert result["generator_name"] == "api_strategy_generator"
    assert result["class_name"] == "ApiMaStrategy"


def test_backend_services_do_not_import_strategy_generation_internals() -> None:
    services_root = Path(__file__).resolve().parents[1] / "backend" / "services"
    for path in services_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "strategy_generation.generators" not in source
        assert "LegacyAgentGenerator" not in source
