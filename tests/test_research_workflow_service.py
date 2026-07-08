from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from backend.services import query_service, research_workflow_service, strategy_generation_service
from data_manager import market_repository


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def _fake_success(source_text: str, options: dict | None = None) -> dict:
    return {
        "success": True,
        "source_text": source_text,
        "strategy_name": "Workflow Strategy",
        "class_name": "WorkflowStrategy",
        "strategy_code": "class WorkflowStrategy:\n    pass\n",
        "params": {"fixed_size": 1},
        "spec": {"strategy_name": "Workflow Strategy"},
        "diagnostics": [{"stage": "mock", "level": "info", "message": "ok"}],
        "generator_name": "mock",
        "generator_version": "test",
        "error": None,
    }


def _fake_real_success(source_text: str, options: dict | None = None) -> dict:
    return {
        "success": True,
        "source_text": source_text,
        "strategy_name": "Real Workflow Strategy",
        "class_name": "RealWorkflowStrategy",
        "strategy_code": """
from vnpy_ctastrategy import CtaTemplate


class RealWorkflowStrategy(CtaTemplate):
    author = "test"
    fixed_size = 1
    parameters = ["fixed_size"]
    variables = []

    def on_init(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_tick(self, tick):
        pass

    def on_bar(self, bar):
        pass
""",
        "params": {"fixed_size": 1},
        "spec": {"strategy_name": "Real Workflow Strategy"},
        "diagnostics": [{"stage": "mock", "level": "info", "message": "ok"}],
        "generator_name": "mock",
        "generator_version": "test",
        "error": None,
    }


def test_create_strategy_research_run(monkeypatch) -> None:
    strategy_dir = None
    run_path = None
    monkeypatch.setattr(strategy_generation_service, "generate_strategy_from_text", _fake_success)
    try:
        result = research_workflow_service.create_strategy_research_run(
            "workflow source",
            config_payload={"vt_symbol": "510300.SSE", "interval": "1m", "mode": "mock"},
            baseline_result_payload={"metrics": {"annual_return": 1.2, "sharpe": 0.8}},
            daily_results=[{"date": "2024-01-01", "balance": 100000.0}],
            trades=[{"datetime": "2024-01-01T10:00:00", "price": 1.0}],
        )
        assert result["error"] is None
        generation = result["generation"]
        baseline = result["baseline"]
        strategy_dir = Path(generation["strategy"]["code_path"]).parent
        run_path = Path(baseline["run"]["runtime_path"])

        detail = query_service.get_run_detail(baseline["run"]["run_id"])
        assert detail["run"]["run_id"] == baseline["run"]["run_id"]
        assert detail["input"]["source_text"] == "workflow source"
        assert detail["config"]["vt_symbol"] == "510300.SSE"
        assert detail["config"]["execution_mode"] == "mock_baseline"
        assert detail["config"]["is_real_backtest"] is False
        assert detail["variants"][0]["variant_name"] == "baseline"
        curve = query_service.get_variant_curve(baseline["run"]["run_id"], "baseline")
        assert curve["data"][0]["date"] == "2024-01-01"
    finally:
        if run_path is not None and run_path.exists():
            shutil.rmtree(run_path)
        if strategy_dir is not None and strategy_dir.exists():
            shutil.rmtree(strategy_dir)


def test_create_strategy_research_run_real_mode(monkeypatch) -> None:
    symbol = f"W{uuid4().hex[:8]}"
    strategy_dir = None
    run_path = None
    monkeypatch.setattr(strategy_generation_service, "generate_strategy_from_text", _fake_real_success)
    market_repository.upsert_bars(
        symbol,
        "SSE",
        "1m",
        [
            {"datetime": "2024-01-02T09:31:00", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000},
            {"datetime": "2024-01-03T09:31:00", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1000},
        ],
    )
    try:
        result = research_workflow_service.create_strategy_research_run(
            "real workflow source",
            config_payload={
                "vt_symbol": f"{symbol}.SSE",
                "interval": "1m",
                "mode": "real",
                "start_date": "2024-01-02T09:31:00",
                "end_date": "2024-01-03T09:31:00",
            },
        )
        assert result["error"] is None
        assert result["execution_mode"] == "real_backtest"
        assert result["is_real_backtest"] is True
        generation = result["generation"]
        baseline = result["baseline"]
        strategy_dir = Path(generation["strategy"]["code_path"]).parent
        run_path = Path(baseline["run"]["runtime_path"])
        detail = query_service.get_run_detail(baseline["run"]["run_id"])
        assert detail["config"]["execution_mode"] == "real_backtest"
        assert detail["config"]["is_real_backtest"] is True
        curve = query_service.get_variant_curve(baseline["run"]["run_id"], "baseline")
        assert curve["data"]
    finally:
        if run_path is not None and run_path.exists():
            shutil.rmtree(run_path)
        if strategy_dir is not None and strategy_dir.exists():
            shutil.rmtree(strategy_dir)
