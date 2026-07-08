from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from backend.repositories import artifact_repository
from backend.services import optimization_service, query_service, run_service, strategy_service


STRATEGY_CODE = """
class OptimizableStrategy:
    fixed_size = 1
    open_hour = 9
    window = 20
    threshold = 1.0
    parameters = ["fixed_size", "open_hour", "window", "threshold"]
    variables = []
"""


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def _create_run() -> tuple[dict, Path, Path]:
    strategy = strategy_service.register_generated_strategy("Optimizable", "source", STRATEGY_CODE)
    strategy_dir = Path(strategy["code_path"]).parent
    (strategy_dir / "generation_report.json").write_text(
        json.dumps(
            {
                "class_name": "OptimizableStrategy",
                "params": {"fixed_size": 1, "open_hour": 9, "window": 20, "threshold": 1.0},
                "spec": {"parameters": {"window": {"description": "lookback"}}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    baseline = run_service.create_baseline_run(
        strategy_id=strategy["strategy_id"],
        strategy_name=strategy["strategy_name"],
        source_text="source",
        config_payload={"vt_symbol": "510300.SSE", "interval": "1m", "mode": "real"},
        strategy_code=STRATEGY_CODE,
        result_payload={"metrics": {"sharpe": 0.0}},
        daily_results=[{"date": "2024-01-01", "balance": 100000, "close_price": 1.0}],
        trades=[],
    )
    return baseline, strategy_dir, Path(baseline["run"]["runtime_path"])


def test_search_space_and_manual_grid_create_variant(monkeypatch) -> None:
    baseline, strategy_dir, run_path = _create_run()

    def fake_backtest(strategy_code, class_name, vt_symbol, parameters, config):
        score = float(parameters["window"])
        return {
            "success": True,
            "metrics": {"sharpe": score},
            "daily_results": [{"date": "2024-01-01", "balance": 100000 + score, "close_price": 1.0}],
            "trades": [],
            "diagnostics": [],
            "error": None,
        }

    import strategy_optimization.optimizers.manual_grid as optimizer_module

    monkeypatch.setattr(optimizer_module.backtesting, "run_backtest", fake_backtest)
    try:
        space = optimization_service.get_search_space(baseline["run"]["run_id"])
        assert [item["name"] for item in space["parameters"]] == ["window", "threshold"]
        assert "fixed_size" in [item["name"] for item in space["hidden_parameters"]]

        result = optimization_service.run_optimization(
            run_id=baseline["run"]["run_id"],
            method="manual_grid",
            selected_parameters=["window"],
            parameter_ranges={"window": {"low": 10, "high": 30, "step": 10, "type": "int"}},
        )
        assert result["error"] is None
        assert result["variant"]["variant_name"] == "manual_grid"
        assert Path(result["artifact_paths"]["grid_summary_path"]).exists()
        assert artifact_repository.list_artifacts("variant", result["variant"]["variant_id"])
        curve = query_service.get_variant_curve(baseline["run"]["run_id"], "manual_grid")
        assert curve["data"]
    finally:
        if run_path.exists():
            shutil.rmtree(run_path)
        if strategy_dir.exists():
            shutil.rmtree(strategy_dir)


def test_optimization_rejects_hidden_parameter() -> None:
    baseline, strategy_dir, run_path = _create_run()
    try:
        try:
            optimization_service.run_optimization(
                run_id=baseline["run"]["run_id"],
                method="manual_grid",
                selected_parameters=["fixed_size"],
                parameter_ranges={"fixed_size": {"low": 1, "high": 2, "step": 1, "type": "int"}},
            )
        except ValueError as exc:
            assert "not tunable" in str(exc)
        else:
            raise AssertionError("hidden parameter should be rejected")
    finally:
        if run_path.exists():
            shutil.rmtree(run_path)
        if strategy_dir.exists():
            shutil.rmtree(strategy_dir)
