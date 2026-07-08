from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import run_service, strategy_service


STRATEGY_CODE = """
class ApiOptimizableStrategy:
    fixed_size = 1
    window = 20
    parameters = ["fixed_size", "window"]
    variables = []
"""


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def test_optimization_api_flow(monkeypatch) -> None:
    strategy = strategy_service.register_generated_strategy("API Optimizable", "source", STRATEGY_CODE)
    strategy_dir = Path(strategy["code_path"]).parent
    (strategy_dir / "generation_report.json").write_text(
        json.dumps({"class_name": "ApiOptimizableStrategy", "params": {"fixed_size": 1, "window": 20}}, ensure_ascii=False),
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
    run_path = Path(baseline["run"]["runtime_path"])

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
    client = TestClient(app)
    try:
        runs = client.get("/api/runs")
        assert runs.status_code == 200
        assert any(item["run_id"] == baseline["run"]["run_id"] for item in runs.json()["runs"])

        methods = client.get("/api/optimization/methods")
        assert methods.status_code == 200
        assert any(item["method"] == "manual_grid" for item in methods.json()["methods"])

        space = client.post("/api/optimization/search-space", json={"run_id": baseline["run"]["run_id"]})
        assert space.status_code == 200
        assert space.json()["parameters"][0]["name"] == "window"

        optimized = client.post(
            "/api/optimization/run",
            json={
                "run_id": baseline["run"]["run_id"],
                "method": "manual_grid",
                "selected_parameters": ["window"],
                "parameter_ranges": {"window": {"low": 10, "high": 30, "step": 10, "type": "int"}},
            },
        )
        assert optimized.status_code == 200
        assert optimized.json()["selected_variant"] == "manual_grid"

        curve = client.get(f"/api/runs/{baseline['run']['run_id']}/variants/manual_grid/curve")
        assert curve.status_code == 200
        assert curve.json()["data"]
    finally:
        if run_path.exists():
            shutil.rmtree(run_path)
        if strategy_dir.exists():
            shutil.rmtree(strategy_dir)
