from __future__ import annotations

from backend.strategy_optimization.optimizers.optuna_tpe import OptunaOptimizer
from backend.strategy_optimization.optimizers.registry import get_optimizer, list_methods


def test_optuna_is_registered():
    methods = {item["method"] for item in list_methods()}

    assert "optuna" in methods
    assert isinstance(get_optimizer("optuna"), OptunaOptimizer)


def test_optuna_exhausts_small_discrete_space_without_duplicate_trials(monkeypatch):
    progress: list[tuple[int, int, str]] = []

    def fake_backtest(**kwargs):
        fast = int(kwargs["parameters"]["fast_window"])
        return {
            "success": True,
            "metrics": {"sharpe": float(fast)},
            "daily_results": [],
            "trades": [],
            "error": None,
        }

    monkeypatch.setattr("backend.strategy_optimization.optimizers.optuna_tpe.backtesting.run_backtest", fake_backtest)
    result = OptunaOptimizer().optimize(
        strategy_code="class Demo: pass",
        class_name="Demo",
        vt_symbol="511380.SSE",
        base_parameters={"fast_window": 1},
        parameter_space={"fast_window": {"low": 1, "high": 3, "step": 1, "type": "int"}},
        backtest_config={},
        objective="sharpe",
        options={
            "selected_parameters": ["fast_window"],
            "max_trials": 6,
            "seed": 7,
            "progress_callback": lambda current, total, message: progress.append((current, total, message)),
        },
    )

    assert result["success"] is True
    assert result["recommended"]["parameters"]["fast_window"] == 3
    assert len(result["candidates"]) == 3
    assert result["sampling_mode"] == "exhaustive_grid"
    assert result["requested_trials"] == 6
    assert result["executed_trials"] == 3
    assert result["search_space_size"] == 3
    assert progress[0][0] == 0
    assert progress[-1][:2] == (3, 3)


def test_optuna_maps_virtual_time_parameter_before_backtest(monkeypatch):
    received: list[dict] = []

    def fake_backtest(**kwargs):
        received.append(dict(kwargs["parameters"]))
        return {"success": True, "metrics": {"sharpe": 1.0}, "daily_results": [], "trades": [], "error": None}

    monkeypatch.setattr("backend.strategy_optimization.optimizers.optuna_tpe.backtesting.run_backtest", fake_backtest)
    result = OptunaOptimizer().optimize(
        strategy_code="class Demo: pass",
        class_name="Demo",
        vt_symbol="511380.SSE",
        base_parameters={"daily_end_hour": 14, "daily_end_minute": 57},
        parameter_space={},
        backtest_config={},
        options={
            "selected_parameters": ["daily_end_time"],
            "max_trials": 1,
            "virtual_parameters": [{
                "name": "daily_end_time",
                "type": "categorical",
                "choices": ["14:40"],
                "maps_to": ["daily_end_hour", "daily_end_minute"],
            }],
        },
    )

    assert result["success"] is True
    assert received[0]["daily_end_hour"] == 14
    assert received[0]["daily_end_minute"] == 40
    assert "daily_end_time" not in received[0]
