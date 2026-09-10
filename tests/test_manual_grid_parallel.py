from __future__ import annotations

from backend.strategy_optimization.optimizers.common import candidate_grid
from backend.strategy_optimization.optimizers.manual_grid import ManualGridOptimizer, _trade_diagnostics


def test_trade_diagnostics_builds_compact_round_trip_metrics() -> None:
    trades = [
        {"direction": "Short", "offset": "Open", "price": 10, "volume": 1, "datetime": "2026-07-01T09:00:00"},
        {"direction": "Long", "offset": "Close", "price": 8, "volume": 1, "datetime": "2026-07-01T10:00:00"},
        {"direction": "Long", "offset": "Open", "price": 8, "volume": 1, "datetime": "2026-07-01T15:00:00"},
        {"direction": "Short", "offset": "Close", "price": 7, "volume": 1, "datetime": "2026-07-02T10:00:00"},
    ]

    metrics = _trade_diagnostics(trades)

    assert metrics["closed_trade_count"] == 2
    assert metrics["trade_win_rate"] == 50
    assert metrics["profit_loss_ratio"] == 2
    assert metrics["profit_factor"] == 2
    assert metrics["gross_expectancy"] == 0.5
    assert metrics["average_holding_minutes"] == 600
    assert metrics["median_holding_minutes"] == 600
    assert metrics["overnight_trade_count"] == 1


def test_manual_grid_without_ranges_runs_base_parameters_once() -> None:
    candidates, diagnostics = candidate_grid(
        {"window": 20, "threshold": 1.5},
        {},
        selected_parameters=[],
    )

    assert candidates == [
        {
            "label": "candidate_001",
            "parameters": {"window": 20, "threshold": 1.5},
            "overrides": {},
        }
    ]
    assert any("base parameters once" in item["message"] for item in diagnostics)


def test_manual_grid_blank_range_uses_selected_parameter_default_once() -> None:
    candidates, diagnostics = candidate_grid(
        {"window": 20, "threshold": 1.5},
        {"window": {"low": None, "high": None, "step": None}},
        selected_parameters=["window"],
    )

    assert candidates[0]["parameters"] == {"window": 20, "threshold": 1.5}
    assert candidates[0]["overrides"] == {"window": 20}
    assert any("using its base value once" in item["message"] for item in diagnostics)


def test_manual_grid_missing_range_uses_selected_parameter_default_once() -> None:
    candidates, _diagnostics = candidate_grid(
        {"window": 20, "threshold": 1.5},
        {},
        selected_parameters=["window"],
    )

    assert candidates[0]["parameters"] == {"window": 20, "threshold": 1.5}
    assert candidates[0]["overrides"] == {"window": 20}


def test_manual_grid_process_pool_preserves_candidate_order_and_progress() -> None:
    progress: list[tuple[int, int]] = []

    result = ManualGridOptimizer().optimize(
        strategy_code="class Demo: pass",
        class_name="Demo",
        vt_symbol="511380.SSE",
        base_parameters={"window": 1},
        parameter_space={"window": {"low": 1, "high": 4, "step": 1, "type": "int"}},
        backtest_config={"mode": "mock"},
        objective="sharpe",
        options={
            "method": "manual_grid",
            "selected_parameters": ["window"],
            "max_trials": 4,
            "max_workers": 2,
            "progress_callback": lambda current, total, _message: progress.append((current, total)),
        },
    )

    assert result["success"] is True
    assert [item["label"] for item in result["candidates"]] == [
        "candidate_001",
        "candidate_002",
        "candidate_003",
        "candidate_004",
    ]
    assert progress[0] == (0, 4)
    assert progress[-1] == (4, 4)
    assert sorted(current for current, _total in progress[1:]) == [1, 2, 3, 4]
    assert any(item.get("max_workers") == 2 for item in result["diagnostics"])


def test_non_manual_delegation_stays_sequential() -> None:
    result = ManualGridOptimizer().optimize(
        strategy_code="class Demo: pass",
        class_name="Demo",
        vt_symbol="511380.SSE",
        base_parameters={"window": 1},
        parameter_space={"window": [1, 2]},
        backtest_config={"mode": "mock"},
        options={"method": "auto", "selected_parameters": ["window"], "max_workers": 4},
    )

    assert result["success"] is True
    assert any(item.get("max_workers") == 1 for item in result["diagnostics"])


def test_manual_grid_returns_every_successful_candidate_curve() -> None:
    result = ManualGridOptimizer().optimize(
        strategy_code="class Demo: pass",
        class_name="Demo",
        vt_symbol="511380.SSE",
        base_parameters={"window": 1},
        parameter_space={"window": {"low": 1, "high": 12, "step": 1, "type": "int"}},
        backtest_config={"mode": "mock"},
        objective="sharpe",
        options={"method": "manual_grid", "selected_parameters": ["window"], "max_trials": 12, "max_workers": 1},
    )

    assert result["success"] is True
    assert len(result["candidate_curves"]) == 12
    assert {item["label"] for item in result["candidate_curves"]} == {
        f"candidate_{index:03d}" for index in range(1, 13)
    }
