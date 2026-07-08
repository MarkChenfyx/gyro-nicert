from __future__ import annotations

from strategy_optimization.parameter_policy import default_range_for_parameter, hidden_reason, is_visible_parameter
from strategy_optimization.search_space import build_parameter_inventory


STRATEGY_CODE = """
class DemoStrategy:
    fixed_size = 1
    open_hour = 9
    breakout_window = 20
    trailing_percent = 1.0
    parameters = ["fixed_size", "open_hour", "breakout_window", "trailing_percent"]
    variables = []
"""


def test_parameter_policy_hides_system_and_time_parameters() -> None:
    assert is_visible_parameter("fixed_size", 1) is False
    assert hidden_reason("open_hour", 9) == "market_session"
    assert is_visible_parameter("breakout_window", 20) is True
    assert default_range_for_parameter("breakout_window", 20) == {"low": 16, "high": 24, "step": 2, "type": "int"}


def test_search_space_uses_report_and_strategy_parameters() -> None:
    report = {
        "class_name": "DemoStrategy",
        "params": {"fixed_size": 1, "open_hour": 9, "breakout_window": 20, "trailing_percent": 1.0},
        "spec": {"parameters": {"breakout_window": {"description": "window"}}},
    }
    inventory = build_parameter_inventory(strategy_code=STRATEGY_CODE, generation_report=report)

    names = [item["name"] for item in inventory["parameters"]]
    hidden_names = [item["name"] for item in inventory["hidden_parameters"]]
    assert names == ["breakout_window", "trailing_percent"]
    assert "fixed_size" in hidden_names
    assert "open_hour" in hidden_names
    assert inventory["parameters"][0]["description"] == "window"
