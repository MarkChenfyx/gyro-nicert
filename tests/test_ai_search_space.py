from __future__ import annotations

import json

from strategy_optimization.range_generation.api_generator import suggest_search_space
from strategy_optimization.range_generation.validator import validate_ai_search_space
from strategy_optimization.search_space import build_parameter_inventory


CODE = '''
class DemoStrategy:
    setup_coef = 0.25
    break_coef = 0.35
    fixed_size = 1
    load_bars = 20
    daily_end_hour = 14
    daily_end_minute = 57
    runtime_value = 0.0
    parameters = ["setup_coef", "break_coef", "fixed_size", "load_bars", "daily_end_hour", "daily_end_minute"]
    variables = ["runtime_value"]
'''


class FakeProvider:
    def complete(self, _messages):
        return json.dumps({
            "parameters": [
                {"name": "setup_coef", "category": "signal_threshold", "optimize": True, "type": "float", "low": 0.18, "high": 0.32, "step": 0.02, "reason": "核心信号"},
                {"name": "break_coef", "category": "signal_threshold", "optimize": True, "type": "float", "low": 0.3, "high": 0.5, "step": 0.02},
                {"name": "load_bars", "category": "warmup", "optimize": False, "type": "int", "reason": "预热参数"},
                {"name": "invented", "optimize": True, "type": "int", "low": 1, "high": 3, "step": 1},
            ],
            "constraints": [{"expression": "setup_coef < break_coef", "type": "hard"}],
            "virtual_parameters": [{
                "name": "daily_end_time", "type": "categorical",
                "choices": ["14:40", "14:57", "99:99"],
                "maps_to": ["daily_end_hour", "daily_end_minute"],
            }],
            "warnings": [],
        })


def test_ai_suggestion_is_validated_against_declared_parameters():
    inventory = build_parameter_inventory(strategy_code=CODE)
    result = suggest_search_space(
        strategy_code=CODE,
        inventory=inventory,
        provider=FakeProvider(),
    )

    assert result["source"] == "ai"
    assert result["fallback_used"] is False
    assert {item["name"] for item in result["parameters"]} == {"setup_coef", "break_coef"}
    assert any(item["name"] == "load_bars" and item["optimize"] is False for item in result["excluded_parameters"])
    assert all(item["name"] != "invented" for item in result["parameters"])
    assert result["constraints"][0]["operator"] == "<"
    assert result["virtual_parameters"][0]["choices"] == ["14:40", "14:57"]


def test_ai_failure_falls_back_to_static_space():
    class FailedProvider:
        def complete(self, _messages):
            raise TimeoutError("model timeout")

    inventory = build_parameter_inventory(strategy_code=CODE)
    result = suggest_search_space(strategy_code=CODE, inventory=inventory, provider=FailedProvider())

    assert result["source"] == "static"
    assert result["fallback_used"] is True
    assert result["parameters"]
    assert "model timeout" in result["diagnostics"][0]["message"]


def test_validator_removes_floating_point_noise_near_zero():
    inventory = {
        "parameters": [{
            "name": "price_buffer", "current": 0.0, "role": "signal_threshold",
            "low": 0.0, "high": 0.01, "step": 0.001, "type": "float",
        }],
        "hidden_parameters": [],
    }
    result = validate_ai_search_space({
        "parameters": [{
            "name": "price_buffer", "optimize": True, "type": "float",
            "low": 0.0000000001, "high": 0.0050000000000001, "step": 0.0010000000000001,
        }]
    }, inventory)

    parameter = result["parameters"][0]
    assert parameter["low"] == 0.0
    assert parameter["high"] == 0.005
    assert parameter["step"] == 0.001
