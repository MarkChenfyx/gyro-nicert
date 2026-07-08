from __future__ import annotations

from strategy_optimization import optimize_parameters


STRATEGY_CODE = """
from vnpy_ctastrategy import CtaTemplate


class DemoStrategy(CtaTemplate):
    fixed_size = 1
    window = 20
    threshold = 1.0
    parameters = ["fixed_size", "window", "threshold"]
    variables = []
"""


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


def test_optimize_parameters_real_mode_uses_legacy_adapter_without_storage(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_backtest(strategy_code, class_name, vt_symbol, parameters, config):
        calls.append(dict(parameters))
        window = int(parameters["window"])
        score = 10 - abs(window - 30)
        return {
            "success": True,
            "metrics": {"sharpe": score, "total_return": score / 10},
            "daily_results": [],
            "trades": [],
            "diagnostics": [],
            "error": None,
        }

    import strategy_optimization.optimizers.manual_grid as optimizer_module

    monkeypatch.setattr(optimizer_module.backtesting, "run_backtest", fake_backtest)

    result = optimize_parameters(
        strategy_code=STRATEGY_CODE,
        class_name="DemoStrategy",
        vt_symbol="510300.SSE",
        base_parameters={"fixed_size": 1, "window": 20, "threshold": 1.0},
        parameter_space={"window": [10, 20, 30]},
        backtest_config={"mode": "real"},
        options={"method": "manual_grid", "selected_parameters": ["window"]},
    )

    assert result["success"] is True
    assert result["recommended"]["parameters"]["window"] == 30
    assert result["recommended"]["score"] == 10
    assert result["candidates"]
    assert result["grid_summary"][0]["rank"] == 1
    assert result["optimizer_name"] == "manual_grid_optimizer"
    assert calls
    assert "strategy_code" not in result
    assert "modified_strategy_code" not in result


def test_optimize_parameters_ignores_frozen_sizing_parameters(monkeypatch) -> None:
    def fake_backtest(strategy_code, class_name, vt_symbol, parameters, config):
        return {
            "success": True,
            "metrics": {"sharpe": float(parameters["window"])},
            "diagnostics": [],
            "error": None,
        }

    import strategy_optimization.optimizers.manual_grid as optimizer_module

    monkeypatch.setattr(optimizer_module.backtesting, "run_backtest", fake_backtest)

    result = optimize_parameters(
        strategy_code=STRATEGY_CODE,
        class_name="DemoStrategy",
        vt_symbol="510300.SSE",
        base_parameters={"fixed_size": 3, "window": 20},
        parameter_space={"fixed_size": [1, 2, 3], "window": [20, 30]},
        backtest_config={"mode": "real"},
        options={"method": "manual_grid", "selected_parameters": ["window"]},
    )

    assert result["success"] is True
    assert result["recommended"]["parameters"]["fixed_size"] == 3
    assert result["recommended"]["parameters"]["window"] == 30
