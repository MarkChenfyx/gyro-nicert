from __future__ import annotations

import shutil

from backend.services.artifact_service import (
    create_pool_snapshot,
    create_run_artifact,
    save_run_config,
    save_run_input,
    save_strategy_code_to_run,
    save_variant_result,
)


def test_storage_contract_runtime_and_pool_snapshot() -> None:
    pool_path = None
    run_path = None
    run = create_run_artifact(
        "baseline",
        "strategy_demo",
        "Demo Strategy",
        "unit-test",
    )
    run_id = run["run_id"]
    run_path = run["run_path"]
    manifest_path = run["manifest_path"]

    assert run_path.exists()
    assert manifest_path.exists()
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert '"run_id":' in manifest_text
    assert '"run_type": "baseline"' in manifest_text
    assert '"strategy_id": "strategy_demo"' in manifest_text

    input_path = save_run_input(run_id, {"source_text": "buy when price breaks high"})
    config_path = save_run_config(run_id, {"vt_symbol": "510300.SSE", "interval": "1m"})
    strategy_path = save_strategy_code_to_run(run_id, "class DemoStrategy:\n    pass\n")
    assert input_path.exists()
    assert config_path.exists()
    assert strategy_path.exists()

    variant = save_variant_result(
        run_id,
        "baseline",
        {"annual_return": 12.3, "sharpe": 1.4},
        daily_results=[
            {"date": "2024-01-01", "balance": 100000.0, "close_price": 1.0},
            {"date": "2024-01-02", "balance": 101000.0, "close_price": 1.1},
        ],
        trades=[
            {"datetime": "2024-01-02T10:00:00", "direction": "long", "price": 1.1},
        ],
    )
    assert variant["result_path"].exists()
    assert variant["daily_results_path"].exists()
    assert variant["trades_path"].exists()

    try:
        pool = create_pool_snapshot(run_id, "baseline", tags=["demo"], note="accepted")
        pool_path = pool["pool_path"]
        assert (pool_path / "manifest.json").exists()
        assert (pool_path / "input.json").exists()
        assert (pool_path / "config.json").exists()
        assert (pool_path / "strategy.py").exists()
        assert (pool_path / "result.json").exists()
        assert (pool_path / "daily_results.csv").exists()
        assert (pool_path / "trades.csv").exists()
        assert (pool_path / "tags.json").exists()
        assert (pool_path / "notes.md").exists()

        shutil.rmtree(run_path)
        assert not run_path.exists()
        assert (pool_path / "result.json").exists()
        assert (pool_path / "strategy.py").exists()
        assert (pool_path / "daily_results.csv").exists()
    finally:
        if run_path is not None and run_path.exists():
            shutil.rmtree(run_path)
        if pool_path is not None and pool_path.exists():
            shutil.rmtree(pool_path)
