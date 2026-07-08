from __future__ import annotations

from pathlib import Path

from strategy_generation import generate_strategy_from_text


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


def test_generate_strategy_from_text_returns_stable_success_contract() -> None:
    result = generate_strategy_from_text("moving average breakout strategy", options={"strategy_name": "MA Breakout"})

    assert set(result) == REQUIRED_KEYS
    assert result["success"] is True
    assert result["source_text"] == "moving average breakout strategy"
    assert result["strategy_name"] == "MA Breakout"
    assert result["class_name"]
    assert "class " in result["strategy_code"]
    assert result["params"]["fixed_size"] == 1
    assert result["spec"]["schema"] == "strategy_generation.strategy_spec.v1"
    assert result["diagnostics"]
    assert result["generator_name"] == "legacy_agent_generator"
    assert result["generator_version"]
    assert result["error"] is None


def test_generate_strategy_from_text_failure_contract() -> None:
    result = generate_strategy_from_text("   ")

    assert set(result) == REQUIRED_KEYS
    assert result["success"] is False
    assert result["strategy_code"] is None
    assert result["error"] == "source_text is empty"
    assert result["diagnostics"][0]["level"] == "error"


def test_backend_services_do_not_import_strategy_generation_internals() -> None:
    services_root = Path(__file__).resolve().parents[1] / "backend" / "services"
    for path in services_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "strategy_generation.generators" not in source
        assert "LegacyAgentGenerator" not in source
