from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace
import pytest

from backend.services import strategy_research_service, walk_forward_research_service


def test_build_windows_uses_rolling_24_month_training_and_6_month_tests() -> None:
    windows = walk_forward_research_service._build_windows(
        date(2022, 1, 1),
        date(2024, 12, 31),
        training_months=24,
        test_months=6,
    )

    assert windows == [
        {
            "train_start": "2022-01-01",
            "train_end": "2023-12-31",
            "test_start": "2024-01-01",
            "test_end": "2024-06-30",
        },
        {
            "train_start": "2022-07-01",
            "train_end": "2024-06-30",
            "test_start": "2024-07-01",
            "test_end": "2024-12-31",
        },
    ]


def test_parameter_rank_analysis_detects_reversal_and_group_monotonicity() -> None:
    training_rows = [
        {
            "label": f"candidate_{index}",
            "parameters": {"alpha": index},
            "score": float(index),
            "sharpe": float(index),
            "success": True,
        }
        for index in range(1, 6)
    ]
    test_rows = [
        {
            "label": f"candidate_{index}",
            "parameters": {"alpha": index},
            "score": float(6 - index),
            "sharpe": float(6 - index),
            "success": True,
        }
        for index in range(1, 6)
    ]

    result = walk_forward_research_service._parameter_rank_analysis(
        training_rows,
        test_rows,
        objective="sharpe",
    )

    assert result["combination_count"] == 5
    assert result["rank_ic"] == -1.0
    assert result["monotonicity"] == -1.0
    assert result["top_20_count"] == 1
    assert result["top_20_lift"] == -2.0
    assert result["training_best_test_percentile"] == 0.0
    assert result["selection_regret"] == 4.0
    assert [group["label"] for group in result["groups"]] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert [group["test_score_mean"] for group in result["groups"]] == [5.0, 4.0, 3.0, 2.0, 1.0]


def test_parameter_rank_analysis_keeps_tied_training_scores_in_the_same_group() -> None:
    training_rows = [
        {"label": "a", "parameters": {"alpha": 1}, "score": 1.0, "sharpe": 1.0, "success": True},
        {"label": "b", "parameters": {"alpha": 2}, "score": 1.0, "sharpe": 1.0, "success": True},
        {"label": "c", "parameters": {"alpha": 3}, "score": 2.0, "sharpe": 2.0, "success": True},
        {"label": "d", "parameters": {"alpha": 4}, "score": 2.0, "sharpe": 2.0, "success": True},
    ]
    test_rows = [
        {"label": "a", "parameters": {"alpha": 1}, "score": 1.0, "sharpe": 1.0, "success": True},
        {"label": "b", "parameters": {"alpha": 2}, "score": 2.0, "sharpe": 2.0, "success": True},
        {"label": "c", "parameters": {"alpha": 3}, "score": 3.0, "sharpe": 3.0, "success": True},
        {"label": "d", "parameters": {"alpha": 4}, "score": 4.0, "sharpe": 4.0, "success": True},
    ]

    result = walk_forward_research_service._parameter_rank_analysis(
        training_rows,
        test_rows,
        objective="sharpe",
    )

    assert result["rank_ic"] == pytest.approx(0.8944271909999159)
    assert [group["label"] for group in result["groups"]] == ["Q1", "Q3"]
    assert [group["count"] for group in result["groups"]] == [2, 2]


def test_walk_forward_optimizes_only_training_period_and_stitches_test_curve(monkeypatch, tmp_path) -> None:
    detail = {
        "pool_item": {"pool_item_id": "pool_1", "strategy_id": "strategy_1", "vt_symbol": "510500.SSE"},
        "config": {
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
            "interval": "1m",
            "capital": 100000,
        },
        "strategy_code": "class DemoStrategy: pass",
    }
    inventory = {"base_parameters": {"alpha": 1, "fixed_size": 1}}
    parameters = [{"name": "alpha", "current": 1, "type": "int", "low": 1, "high": 2, "step": 1}]
    training_configs: list[dict] = []
    test_runs: list[tuple[dict, dict]] = []

    monkeypatch.setattr(walk_forward_research_service.pool_service, "get_pool_item_detail", lambda _pool_item_id: detail)
    monkeypatch.setattr(strategy_research_service, "_safe_pool_path", lambda _detail: tmp_path)
    monkeypatch.setattr(strategy_research_service, "_parameter_inventory", lambda _detail: (inventory, parameters))
    monkeypatch.setattr(strategy_research_service, "_class_name", lambda *_args: "DemoStrategy")
    monkeypatch.setattr(strategy_research_service, "_safe_research_dir", lambda pool_item_id: tmp_path / pool_item_id)
    monkeypatch.setattr(walk_forward_research_service, "RESEARCH_ROOT", tmp_path)

    tasks = {"task_id": "task_1"}
    monkeypatch.setattr(walk_forward_research_service.task_service, "create_task", lambda *_args, **_kwargs: tasks)
    monkeypatch.setattr(walk_forward_research_service.task_service, "mark_running", lambda *_args, **_kwargs: tasks)
    monkeypatch.setattr(walk_forward_research_service.task_service, "mark_progress", lambda *_args, **_kwargs: tasks)
    monkeypatch.setattr(walk_forward_research_service.task_service, "mark_completed", lambda *_args, **_kwargs: tasks)
    monkeypatch.setattr(walk_forward_research_service.task_service, "mark_failed", lambda *_args, **_kwargs: tasks)

    def fake_optimize_parameters(**kwargs):
        backtest_config = dict(kwargs["backtest_config"])
        training_configs.append(backtest_config)
        callback = kwargs["options"]["progress_callback"]
        callback(1, 2, "candidate 1")
        callback(2, 2, "candidate 2")
        is_test_window = str(backtest_config["start_date"]).startswith("2024")
        first_score, second_score = ((0.2, 0.8) if is_test_window else (0.25, 1.25))
        return {
            "success": True,
            "recommended": {
                "parameters": {"alpha": 2, "fixed_size": 1},
                "score": second_score,
                "metrics": {"sharpe": second_score},
            },
            "grid_summary": [
                {
                    "label": "candidate_001",
                    "parameters": {"alpha": 1},
                    "score": first_score,
                    "sharpe": first_score,
                    "success": True,
                },
                {
                    "label": "candidate_002",
                    "parameters": {"alpha": 2},
                    "score": second_score,
                    "sharpe": second_score,
                    "success": True,
                },
            ],
        }

    def fake_run_backtest(**kwargs):
        config = dict(kwargs["config"])
        run_parameters = dict(kwargs["parameters"])
        test_runs.append((config, run_parameters))
        selected_run = run_parameters.get("alpha") == 2
        return {
            "success": True,
            "metrics": {"sharpe": 0.8},
            "daily_results": [
                {"date": config["start_date"], "close_price": 100.0, "net_pnl": 10.0 if selected_run else 2.0},
                {"date": config["end_date"], "close_price": 101.0, "net_pnl": 5.0 if selected_run else 1.0},
            ],
        }

    monkeypatch.setattr(walk_forward_research_service, "optimize_parameters", fake_optimize_parameters)
    monkeypatch.setattr(walk_forward_research_service.backtesting, "run_backtest", fake_run_backtest)

    result = walk_forward_research_service.run_pool_walk_forward(
        "pool_1",
        training_start_date="2022-01-01",
        training_months=24,
        test_months=6,
        selected_parameters=["alpha"],
        parameter_ranges={"alpha": {"low": 1, "high": 2, "step": 1}},
        objective="sharpe",
        max_trials=100,
    )

    assert [(item["start_date"], item["end_date"]) for item in training_configs] == [
        ("2022-01-01", "2023-12-31"),
        ("2022-07-01", "2024-06-30"),
    ]
    assert [(item["start_date"], item["end_date"], params["alpha"]) for item, params in test_runs] == [
        ("2024-01-01", "2024-06-30", 2),
        ("2024-01-01", "2024-06-30", 1),
        ("2024-07-01", "2024-12-31", 2),
        ("2024-07-01", "2024-12-31", 1),
    ]
    assert all(window["train_end"] < window["test_start"] for window in result["windows"])
    assert [row["date"] for row in result["curve"]] == [
        "2024-01-01",
        "2024-06-30",
        "2024-07-01",
        "2024-12-31",
    ]
    assert result["window_count"] == 2
    assert result["training_start_date"] == "2022-01-01"
    assert result["selected_parameters"] == ["alpha"]
    assert result["windows"][0]["selected_parameters"] == {"alpha": 2}
    assert result["windows"][0]["fixed_test_metrics"]["sharpe"] == 0.8
    assert result["fixed_parameters"]["alpha"] == 1
    assert [row["net_pnl"] for row in result["fixed_curve"]] == [2.0, 1.0, 2.0, 1.0]
    assert result["metrics"]["total_net_pnl"] == 30.0
    assert result["fixed_metrics"]["total_net_pnl"] == 6.0
    assert "parameter_predictability" not in result
    assert all(len(window["training_grid_summary"]) == 2 for window in result["windows"])

    result_files = list((tmp_path / "pool_1").glob("walk_forward_*/result.json"))
    assert len(result_files) == 1
    stored = json.loads(result_files[0].read_text(encoding="utf-8"))
    assert stored["type"] == "walk_forward"
    assert stored["window_count"] == 2

    analysis = walk_forward_research_service.run_walk_forward_rank_analysis("pool_1", result["experiment_id"])

    assert [(item["start_date"], item["end_date"]) for item in training_configs] == [
        ("2022-01-01", "2023-12-31"),
        ("2022-07-01", "2024-06-30"),
        ("2024-01-01", "2024-06-30"),
        ("2024-07-01", "2024-12-31"),
    ]
    assert [window["rank_analysis"]["rank_ic"] for window in analysis["windows"]] == [1.0, 1.0]
    assert analysis["parameter_predictability"]["mean_rank_ic"] == 1.0
    assert analysis["parameter_predictability"]["positive_rank_ic_ratio"] == 1.0
    assert analysis["parameter_predictability"]["mean_top_20_lift"] == pytest.approx(0.3)
    assert analysis["parameter_predictability"]["group_monotonicity"] == 1.0
    assert analysis["cached"] is False

    cached = walk_forward_research_service.run_walk_forward_rank_analysis("pool_1", result["experiment_id"])
    assert cached["cached"] is True
    assert len(training_configs) == 4

    legacy_experiment = "walk_forward_legacy"
    legacy_payload = dict(stored)
    legacy_payload["experiment_id"] = legacy_experiment
    legacy_payload["windows"] = [
        {key: value for key, value in dict(window).items() if key != "training_grid_summary"}
        for window in list(stored["windows"])
    ]
    legacy_dir = tmp_path / "pool_1" / legacy_experiment
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "result.json").write_text(json.dumps(legacy_payload), encoding="utf-8")

    legacy_analysis = walk_forward_research_service.run_walk_forward_rank_analysis("pool_1", legacy_experiment)

    assert legacy_analysis["parameter_predictability"]["mean_rank_ic"] == 1.0
    assert all(len(window["training_grid_summary"]) == 2 for window in legacy_analysis["windows"])
    assert len(training_configs) == 8


def test_ai_research_overview_is_single_line_and_cached(monkeypatch, tmp_path) -> None:
    calls: list[list[dict[str, str]]] = []

    class FakeProvider:
        config = SimpleNamespace(model="test-overview-model")

        def complete(self, messages):
            calls.append(messages)
            return '{"summary":"策略当前取得正累计收益，但仍需要进一步验证结果是否稳定。"}'

    monkeypatch.setattr(strategy_research_service, "build_provider", lambda options=None: FakeProvider())
    monkeypatch.setattr(strategy_research_service, "_safe_pool_path", lambda detail: tmp_path)
    monkeypatch.setattr(strategy_research_service, "_latest_heatmap", lambda pool_item_id: None)
    monkeypatch.setattr(
        walk_forward_research_service,
        "latest_walk_forward_result",
        lambda pool_item_id: None,
    )
    monkeypatch.setattr(
        strategy_research_service,
        "_ai_overview_cache_path",
        lambda pool_item_id: tmp_path / f"{pool_item_id}.json",
    )
    monkeypatch.setattr(
        strategy_research_service.pool_service,
        "get_pool_item_detail",
        lambda pool_item_id: {
            "pool_item": {"pool_item_id": pool_item_id, "strategy_name": "Demo", "vt_symbol": "510300.SSE"},
            "config": {"interval": "1m", "start_date": "2025-01-01", "end_date": "2025-12-31"},
            "result": {"metrics": {"sharpe": 0.8, "total_trade_count": 12}},
            "daily_results": {
                "data": [
                    {"date": "2025-01-01", "close_price": 100, "pre_close": 100, "net_pnl": 1},
                    {"date": "2025-01-02", "close_price": 101, "pre_close": 100, "net_pnl": 2},
                ]
            },
            "trades": {"data": [{"tradeid": str(index)} for index in range(12)]},
        },
    )

    first = strategy_research_service.create_pool_ai_overview("pool_demo")
    cached = strategy_research_service.create_pool_ai_overview("pool_demo")

    assert first["cached"] is False
    assert cached["cached"] is True
    assert "策略当前取得正累计收益" in first["summary"]
    assert first["summary"].endswith(strategy_research_service.AI_OVERVIEW_FIXED_SUGGESTION)
    assert len(calls) == 1
    assert '"trade_count": 12' in calls[0][1]["content"]
