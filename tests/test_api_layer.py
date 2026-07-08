from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import strategy_generation_service
from data_manager import market_repository


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def test_api_layer_end_to_end() -> None:
    client = TestClient(app)
    generated_strategy_dir: Path | None = None
    research_strategy_dir: Path | None = None
    run_path: Path | None = None
    pool_path: Path | None = None
    try:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        generated = client.post("/api/strategies/generate", json={"source_text": "API strategy generation"})
        assert generated.status_code == 200
        generated_payload = generated.json()
        assert generated_payload["task"]["status"] == "completed"
        assert generated_payload["generation"]["strategy_code"]
        generated_strategy_dir = Path(generated_payload["strategy"]["code_path"]).parent

        research = client.post(
            "/api/research/create",
            json={
                "source_text": "API research strategy",
                "symbol": "510300",
                "exchange": "SSE",
                "interval": "1m",
                "mode": "mock",
            },
        )
        assert research.status_code == 200
        research_payload = research.json()
        assert research_payload["execution_mode"] == "mock_baseline"
        assert research_payload["is_real_backtest"] is False
        run_id = research_payload["baseline"]["run"]["run_id"]
        task_id = research_payload["generation"]["task"]["task_id"]
        research_strategy_dir = Path(research_payload["generation"]["strategy"]["code_path"]).parent
        run_path = Path(research_payload["baseline"]["run"]["runtime_path"])

        run = client.get(f"/api/runs/{run_id}")
        assert run.status_code == 200
        run_payload = run.json()
        assert run_payload["run"]["run_id"] == run_id
        assert run_payload["variants"][0]["variant_name"] == "baseline"

        curve = client.get(f"/api/runs/{run_id}/variants/baseline/curve")
        assert curve.status_code == 200
        assert curve.json()["data"]

        pool = client.post(
            "/api/pool/add",
            json={"run_id": run_id, "variant_name": "baseline", "vt_symbol": "510300.SSE", "tags": ["api"]},
        )
        assert pool.status_code == 200
        pool_payload = pool.json()
        pool_item_id = pool_payload["pool_item_id"]
        pool_path = Path(pool_payload["pool_path"])

        pool_list = client.get("/api/pool")
        assert pool_list.status_code == 200
        assert any(item["pool_item_id"] == pool_item_id for item in pool_list.json()["items"])

        pool_detail = client.get(f"/api/pool/{pool_item_id}")
        assert pool_detail.status_code == 200
        assert pool_detail.json()["pool_item"]["pool_item_id"] == pool_item_id

        pool_curve = client.get(f"/api/pool/{pool_item_id}/curve")
        assert pool_curve.status_code == 200
        assert pool_curve.json()["data"]

        tasks = client.get("/api/tasks")
        assert tasks.status_code == 200
        assert any(task["task_id"] == task_id for task in tasks.json()["tasks"])

        task = client.get(f"/api/tasks/{task_id}")
        assert task.status_code == 200
        assert task.json()["task_id"] == task_id
    finally:
        for path in [generated_strategy_dir, research_strategy_dir, run_path, pool_path]:
            if path is not None and path.exists():
                shutil.rmtree(path)


def test_api_research_create_real_mode(monkeypatch) -> None:
    symbol = f"P{uuid4().hex[:8]}"
    client = TestClient(app)
    strategy_dir: Path | None = None
    run_path: Path | None = None

    def fake_generation(source_text: str, options: dict | None = None) -> dict:
        return {
            "success": True,
            "source_text": source_text,
            "strategy_name": "API Real Strategy",
            "class_name": "ApiRealStrategy",
            "strategy_code": """
from vnpy_ctastrategy import CtaTemplate


class ApiRealStrategy(CtaTemplate):
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
            "spec": {"strategy_name": "API Real Strategy"},
            "diagnostics": [],
            "generator_name": "test",
            "generator_version": "test",
            "error": None,
        }

    monkeypatch.setattr(strategy_generation_service, "generate_strategy_from_text", fake_generation)
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
        response = client.post(
            "/api/research/create",
            json={
                "source_text": "API real research strategy",
                "symbol": symbol,
                "exchange": "SSE",
                "interval": "1m",
                "mode": "real",
                "start_date": "2024-01-02T09:31:00",
                "end_date": "2024-01-03T09:31:00",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["error"] is None
        assert payload["execution_mode"] == "real_backtest"
        assert payload["is_real_backtest"] is True
        strategy_dir = Path(payload["generation"]["strategy"]["code_path"]).parent
        run_path = Path(payload["baseline"]["run"]["runtime_path"])
        assert payload["baseline"]["artifact_paths"]["daily_results_path"]
    finally:
        for path in [strategy_dir, run_path]:
            if path is not None and path.exists():
                shutil.rmtree(path)
