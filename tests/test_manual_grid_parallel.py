from __future__ import annotations

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
