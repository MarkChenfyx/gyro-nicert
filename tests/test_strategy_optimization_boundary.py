from __future__ import annotations

from strategy_optimization import optimize_parameters


def test_optimize_parameters_mock_mode_returns_recommended_without_code_changes() -> None:
    result = optimize_parameters(
        strategy_code="class DemoStrategy: pass",
        class_name="DemoStrategy",
        vt_symbol="510300.SSE",
        base_parameters={"fixed_size": 1, "window": 20},
        parameter_space={"window": [10, 20, 30]},
        backtest_config={"mode": "mock"},
        objective="sharpe",
    )

    assert result["success"] is True
    assert result["recommended"]["parameters"] == {"fixed_size": 1, "window": 20}
    assert result["recommended"]["metrics"]
    assert result["candidates"]
    assert result["grid_summary"]
    assert "strategy_code" not in result
    assert "modified_strategy_code" not in result


def test_optimize_parameters_default_mode_is_clear_not_implemented() -> None:
    result = optimize_parameters(
        strategy_code="class DemoStrategy: pass",
        class_name="DemoStrategy",
        vt_symbol="510300.SSE",
        base_parameters={"fixed_size": 1},
        parameter_space={},
        backtest_config={},
    )

    assert result["success"] is False
    assert result["recommended"] is None
    assert result["candidates"] == []
    assert result["grid_summary"] == []
    assert "not implemented" in result["error"]

