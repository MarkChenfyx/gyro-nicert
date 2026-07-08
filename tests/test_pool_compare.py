from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import pool_service, run_service, strategy_service


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def _make_pool_item(name: str, *, with_curve: bool = True) -> tuple[dict, Path, Path, Path]:
    strategy = strategy_service.register_generated_strategy(
        name,
        f"{name} source",
        f"class {name.replace(' ', '')}:\n    pass\n",
    )
    strategy_dir = Path(strategy["code_path"]).parent
    daily_results = [
        {"date": "2024-01-02", "balance": 100000, "close_price": 1.0},
        {"date": "2024-01-03", "balance": 101000, "close_price": 1.1},
    ] if with_curve else None
    baseline = run_service.create_baseline_run(
        strategy_id=strategy["strategy_id"],
        strategy_name=strategy["strategy_name"],
        source_text=f"{name} source",
        config_payload={"vt_symbol": "510300.SSE", "interval": "1m", "parameters": {"window": 20}},
        strategy_code=Path(strategy["code_path"]).read_text(encoding="utf-8"),
        result_payload={
            "metrics": {
                "total_return": 1.0,
                "annual_return": 10.0,
                "max_drawdown": -2.0,
                "sharpe": 1.5,
            },
            "params": {"window": 20},
        },
        daily_results=daily_results,
        trades=[{"datetime": "2024-01-03T10:00:00", "direction": "long", "price": 1.1}],
    )
    run_path = Path(baseline["run"]["runtime_path"])
    pool_item = pool_service.add_variant_to_pool(
        baseline["run"]["run_id"],
        "baseline",
        tags=["compare"],
        note="accepted",
        vt_symbol="510300.SSE",
    )
    pool_path = Path(pool_item["pool_path"])
    return pool_item, strategy_dir, run_path, pool_path


def test_pool_compare_service_reads_snapshots_and_diagnostics() -> None:
    created_paths: list[Path] = []
    try:
        first, first_strategy_dir, first_run_path, first_pool_path = _make_pool_item("Compare One")
        second, second_strategy_dir, second_run_path, second_pool_path = _make_pool_item("Compare Two", with_curve=False)
        created_paths.extend([first_strategy_dir, first_run_path, first_pool_path, second_strategy_dir, second_run_path, second_pool_path])

        payload = pool_service.compare_pool_items([first["pool_item_id"], second["pool_item_id"], "missing_pool_item"])

        assert [item["pool_item_id"] for item in payload["items"]] == [first["pool_item_id"], second["pool_item_id"]]
        assert payload["items"][0]["metrics"]["sharpe"] == 1.5
        assert payload["items"][0]["params"]["window"] == 20
        assert payload["items"][0]["curve"]
        assert payload["items"][0]["trades_preview"]
        assert payload["benchmark"]["label"] == "Buy & Hold"
        assert payload["benchmark"]["curve"][-1]["value"] > 0
        assert any("no daily curve" in item["message"] for item in payload["diagnostics"])
        assert any("not found" in item["message"] for item in payload["diagnostics"])
    finally:
        for path in created_paths:
            if path.exists():
                shutil.rmtree(path)


def test_pool_compare_api_accepts_empty_and_selected_items() -> None:
    client = TestClient(app)
    created_paths: list[Path] = []
    try:
        empty = client.post("/api/pool/compare", json={"pool_item_ids": []})
        assert empty.status_code == 200
        assert empty.json()["items"] == []

        item, strategy_dir, run_path, pool_path = _make_pool_item("Compare API")
        created_paths.extend([strategy_dir, run_path, pool_path])
        response = client.post("/api/pool/compare", json={"pool_item_ids": [item["pool_item_id"]]})

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["pool_item_id"] == item["pool_item_id"]
        assert payload["items"][0]["curve"]
        assert payload["benchmark"]["curve"]
    finally:
        for path in created_paths:
            if path.exists():
                shutil.rmtree(path)
