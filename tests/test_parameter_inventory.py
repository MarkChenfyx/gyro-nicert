from backend.strategy_optimization.search_space import build_parameter_inventory


STRATEGY_CODE = '''
class DemoStrategy:
    fixed_size = 1
    bar_window = 60
    fast_window = 8
    slow_window = 17
    daily_end_hour = 14
    daily_end_minute = 59
    ma_value = 0.0
    entry_price = 0.0
    last_signal = 0
    parameters = ["fixed_size", "bar_window", "fast_window", "slow_window", "daily_end_hour", "daily_end_minute"]
    variables = ["ma_value", "entry_price", "last_signal"]
'''


def test_inventory_only_uses_declared_parameters_and_hides_structural_values():
    inventory = build_parameter_inventory(strategy_code=STRATEGY_CODE)

    assert [item["name"] for item in inventory["parameters"]] == ["fast_window", "slow_window"]
    assert {item["name"] for item in inventory["hidden_parameters"]} == {
        "fixed_size",
        "bar_window",
        "daily_end_hour",
        "daily_end_minute",
    }
    hidden_roles = {item["name"]: item["role"] for item in inventory["hidden_parameters"]}
    assert hidden_roles["daily_end_hour"] == "market_session"
    assert hidden_roles["daily_end_minute"] == "market_session"
    assert "ma_value" not in inventory["base_parameters"]
    assert "entry_price" not in inventory["base_parameters"]
    assert "last_signal" not in inventory["base_parameters"]


def test_inventory_does_not_guess_parameters_when_declaration_is_missing():
    inventory = build_parameter_inventory(
        strategy_code="class DemoStrategy:\n    fast_window = 10\n    ma_value = 0.0\n"
    )

    assert inventory["parameters"] == []
    assert inventory["base_parameters"] == {}
