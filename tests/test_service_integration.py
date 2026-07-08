from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from backend.repositories import artifact_repository
from backend.services import pool_service, query_service, run_service, strategy_service


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def test_service_integration_storage_db_traceability() -> None:
    strategy_dir = None
    run_path = None
    pool_path = None
    try:
        strategy = strategy_service.register_generated_strategy(
            "Integration Strategy",
            "natural language source",
            "class IntegrationStrategy:\n    pass\n",
        )
        strategy_path = Path(strategy["code_path"])
        strategy_dir = strategy_path.parent
        assert strategy_path.exists()
        strategy_artifacts = artifact_repository.list_artifacts("strategy", strategy["strategy_id"])
        assert any(item["artifact_type"] == "strategy_code" for item in strategy_artifacts)

        baseline = run_service.create_baseline_run(
            strategy_id=strategy["strategy_id"],
            strategy_name=strategy["strategy_name"],
            source_text="natural language source",
            config_payload={"vt_symbol": "510300.SSE", "interval": "1m"},
            strategy_code=strategy_path.read_text(encoding="utf-8"),
            result_payload={
                "metrics": {
                    "annual_return": 18.5,
                    "max_drawdown": -4.2,
                    "sharpe": 2.1,
                    "calmar": 4.4,
                }
            },
            daily_results=[
                {"date": "2024-01-01", "balance": 100000.0, "close_price": 1.0},
                {"date": "2024-01-02", "balance": 101500.0, "close_price": 1.1},
            ],
            trades=[
                {"datetime": "2024-01-02T10:00:00", "direction": "long", "price": 1.1},
            ],
        )
        run = baseline["run"]
        variant = baseline["variant"]
        run_path = Path(run["runtime_path"])
        assert baseline["task"]["status"] == "completed"
        assert run_path.exists()
        assert variant["variant_name"] == "baseline"
        assert artifact_repository.list_artifacts("run", run["run_id"])
        assert artifact_repository.list_artifacts("variant", variant["variant_id"])

        detail = query_service.get_run_detail(run["run_id"])
        assert detail["run"]["run_id"] == run["run_id"]
        assert detail["manifest"]["run_id"] == run["run_id"]
        assert detail["input"]["source_text"] == "natural language source"
        assert detail["config"]["vt_symbol"] == "510300.SSE"
        assert detail["variants"][0]["variant_id"] == variant["variant_id"]

        curve = query_service.get_variant_curve(run["run_id"], "baseline")
        assert curve["columns"] == ["date", "balance", "close_price"]
        assert len(curve["data"]) == 2
        trades = query_service.get_variant_trades(run["run_id"], "baseline")
        assert trades["columns"] == ["datetime", "direction", "price"]
        assert len(trades["data"]) == 1

        pool_item = pool_service.add_variant_to_pool(
            run["run_id"],
            "baseline",
            tags=["integration", "phase2"],
            note="accepted",
            vt_symbol="510300.SSE",
        )
        pool_path = Path(pool_item["pool_path"])
        assert pool_item["strategy_id"] == strategy["strategy_id"]
        assert pool_item["sharpe"] == 2.1
        assert pool_path.exists()
        assert artifact_repository.list_artifacts("pool_item", pool_item["pool_item_id"])

        shutil.rmtree(run_path)
        assert not run_path.exists()
        pool_detail = pool_service.get_pool_item_detail(pool_item["pool_item_id"])
        assert pool_detail["result"]["metrics"]["sharpe"] == 2.1
        assert pool_detail["strategy_code"].startswith("class IntegrationStrategy")
        assert Path(pool_detail["daily_results_path"]).exists()

        pool_curve = query_service.get_pool_curve(pool_item["pool_item_id"])
        assert len(pool_curve["data"]) == 2
        listed = pool_service.list_pool_items(
            keyword="Integration",
            vt_symbol="510300.SSE",
            min_sharpe=2.0,
            tag="phase2",
            sort_by="sharpe",
            order="desc",
        )
        assert any(item["pool_item_id"] == pool_item["pool_item_id"] for item in listed)
    finally:
        if run_path is not None and run_path.exists():
            shutil.rmtree(run_path)
        if pool_path is not None and pool_path.exists():
            shutil.rmtree(pool_path)
        if strategy_dir is not None and strategy_dir.exists():
            shutil.rmtree(strategy_dir)

