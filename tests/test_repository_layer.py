from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from backend.repositories import (
    artifact_repository,
    pool_repository,
    run_repository,
    strategy_repository,
    variant_repository,
)


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def test_repository_layer_crud() -> None:
    suffix = uuid4().hex[:8]
    strategy_id = f"strategy_repo_{suffix}"
    run_id = f"run_repo_{suffix}"
    variant_id = f"variant_repo_{suffix}"
    pool_item_id = f"pool_repo_{suffix}"

    strategy = strategy_repository.create_strategy(
        strategy_id,
        f"Repo Strategy {suffix}",
        "generated",
        "source text",
        f"strategies/generated/{strategy_id}/strategy.py",
        "abc123",
    )
    assert strategy["strategy_id"] == strategy_id
    assert strategy_repository.get_strategy(strategy_id)["code_hash"] == "abc123"
    assert any(item["strategy_id"] == strategy_id for item in strategy_repository.list_strategies())

    run = run_repository.create_run(
        run_id,
        strategy_id,
        "task_repo",
        "baseline",
        "running",
        f"storage/runtime/runs/{run_id}",
    )
    assert run["status"] == "running"
    updated_run = run_repository.update_run_status(run_id, "completed")
    assert updated_run["status"] == "completed"
    assert run_repository.get_run(run_id)["strategy_id"] == strategy_id

    variant = variant_repository.create_variant(
        variant_id,
        run_id,
        "baseline",
        "params123",
        "config.json",
        "result.json",
        "daily_results.csv",
        "trades.csv",
    )
    assert variant["variant_id"] == variant_id
    assert variant_repository.get_variant_by_run_and_name(run_id, "baseline")["variant_id"] == variant_id
    assert [item["variant_id"] for item in variant_repository.list_variants(run_id)] == [variant_id]

    pool_item = pool_repository.create_pool_item(
        pool_item_id,
        strategy_id,
        run_id,
        variant_id,
        f"storage/pool/strategies/{pool_item_id}",
        f"Repo Strategy {suffix}",
        vt_symbol="510300.SSE",
        annual_return=11.0,
        max_drawdown=-3.0,
        sharpe=1.7,
        calmar=3.1,
        tags=["repo", suffix],
    )
    assert pool_item["pool_item_id"] == pool_item_id
    assert pool_repository.get_pool_item(pool_item_id)["sharpe"] == 1.7
    filtered = pool_repository.list_pool_items(
        keyword="Repo Strategy",
        vt_symbol="510300.SSE",
        min_sharpe=1.0,
        tag=suffix,
        sort_by="sharpe",
        order="desc",
    )
    assert any(item["pool_item_id"] == pool_item_id for item in filtered)

    artifact = artifact_repository.create_artifact(
        "run",
        run_id,
        "manifest",
        f"storage/runtime/runs/{run_id}/manifest.json",
        sha256="hash",
    )
    assert artifact_repository.get_artifact(artifact["artifact_id"])["sha256"] == "hash"
    assert any(item["artifact_id"] == artifact["artifact_id"] for item in artifact_repository.list_artifacts("run", run_id))

