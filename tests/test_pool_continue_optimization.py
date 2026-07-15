from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import artifact_service, optimization_service, pool_service


def _pool_detail(tmp_path):
    pool_path = tmp_path / "pool_1"
    pool_path.mkdir()
    (pool_path / "input.json").write_text(json.dumps({"source_text": "original source"}), encoding="utf-8")
    return {
        "pool_item": {
            "pool_item_id": "pool_1",
            "pool_path": str(pool_path),
            "strategy_id": "strategy_1",
            "source_run_id": "run_deleted",
            "source_variant_id": "variant_manual_grid",
            "vt_symbol": "511380.SSE",
        },
        "pool_path": str(pool_path),
        "manifest": {
            "class_name": "ExampleStrategy",
            "source_variant_name": "manual_grid",
        },
        "config": {
            "interval": "1m",
            "start_date": "2023-01-03",
            "end_date": "2026-07-15",
            "parameters": {"window": 25},
        },
        "result": {"params": {"window": 10}},
        "strategy_code": "class ExampleStrategy:\n    parameters = ['window']\n    window = 10\n",
    }


def test_continue_optimization_reruns_pool_snapshot_as_new_baseline(tmp_path, monkeypatch):
    detail = _pool_detail(tmp_path)
    captured: dict = {}

    monkeypatch.setattr(pool_service, "get_pool_item_detail", lambda pool_item_id: detail)
    monkeypatch.setattr(
        pool_service.strategy_repository,
        "get_strategy",
        lambda strategy_id: {
            "strategy_id": strategy_id,
            "strategy_name": "Example | v1",
            "strategy_family": "Example",
            "strategy_version": "v1",
            "source_text": "strategy source",
        },
    )
    monkeypatch.setattr(
        pool_service.run_repository,
        "get_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("source run must not be read")),
    )

    def fake_backtest(**kwargs):
        captured["backtest"] = kwargs
        return {
            "success": True,
            "metrics": {"sharpe": 1.2},
            "daily_results": [{"date": "2023-01-03", "net_pnl": 0}],
            "trades": [{"tradeid": "1"}],
        }

    def fake_create_baseline_run(**kwargs):
        captured["baseline"] = kwargs
        return {
            "run": {"run_id": "run_new"},
            "variant": {"variant_name": "baseline"},
        }

    monkeypatch.setattr(pool_service, "run_backtest", fake_backtest)
    monkeypatch.setattr(pool_service.run_service, "create_baseline_run", fake_create_baseline_run)

    result = pool_service.continue_optimization_from_pool("pool_1")

    assert result["baseline"]["run"]["run_id"] == "run_new"
    assert captured["backtest"]["parameters"] == {"window": 25}
    assert captured["backtest"]["strategy_code"] == detail["strategy_code"]
    assert captured["backtest"]["config"]["start_date"] == "2023-01-03"
    assert captured["backtest"]["config"]["end_date"] == "2026-07-15"
    assert captured["baseline"]["result_payload"]["params"] == {"window": 25}
    assert captured["baseline"]["related_pool_item_id"] == "pool_1"
    assert captured["baseline"]["manifest_lineage"] == {
        "source_type": "pool_item",
        "pool_item_id": "pool_1",
        "source_run_id": "run_deleted",
        "source_variant_id": "variant_manual_grid",
        "source_variant_name": "manual_grid",
        "operation": "rerun_as_baseline",
    }


def test_run_manifest_keeps_pool_provenance_nested(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_service, "RUNS_ROOT", tmp_path / "runs")
    strategy = {
        "strategy_id": "strategy_1",
        "strategy_name": "Example | v1",
        "strategy_family": "Example",
        "strategy_version": "v1",
        "class_name": "ExampleStrategy",
    }
    lineage = {
        "source_type": "pool_item",
        "pool_item_id": "pool_1",
        "source_variant_name": "manual_grid",
        "operation": "rerun_as_baseline",
    }

    created = artifact_service.create_run_artifact("baseline", strategy, "service_test", lineage=lineage)
    manifest = json.loads(created["manifest_path"].read_text(encoding="utf-8"))

    assert manifest["lineage"] == lineage
    assert "pool_item_id" not in {key for key in manifest if key != "lineage"}
    assert "source_variant_name" not in {key for key in manifest if key != "lineage"}


def test_pool_baseline_parameters_become_optimization_base_parameters(tmp_path, monkeypatch):
    run_path = tmp_path / "run_new"
    run_path.mkdir()
    (run_path / "strategy.py").write_text(
        "class ExampleStrategy:\n    parameters = ['window']\n    window = 10\n",
        encoding="utf-8",
    )
    (run_path / "config.json").write_text(json.dumps({"vt_symbol": "511380.SSE", "parameters": {"window": 25}}), encoding="utf-8")
    (run_path / "manifest.json").write_text(
        json.dumps({"lineage": {"source_type": "pool_item", "operation": "rerun_as_baseline"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        optimization_service.run_repository,
        "get_run",
        lambda run_id: {"run_id": run_id, "strategy_id": "strategy_1", "runtime_path": str(run_path)},
    )
    monkeypatch.setattr(optimization_service.strategy_repository, "get_strategy", lambda strategy_id: {})

    context = optimization_service._run_context("run_new")

    assert context["inventory"]["base_parameters"]["window"] == 25
    parameter = next(item for item in context["inventory"]["parameters"] if item["name"] == "window")
    assert parameter["current"] == 25
    assert parameter["low"] <= 25 <= parameter["high"]


def test_continue_optimization_api_returns_new_run(monkeypatch):
    monkeypatch.setattr(
        pool_service,
        "continue_optimization_from_pool",
        lambda pool_item_id: {
            "baseline": {"run": {"run_id": "run_new"}, "variant": {"variant_name": "baseline"}},
            "lineage": {"pool_item_id": pool_item_id},
        },
    )

    response = TestClient(app).post("/api/pool/pool_1/continue-optimization")

    assert response.status_code == 200
    assert response.json()["baseline"]["run"]["run_id"] == "run_new"
    assert response.json()["lineage"]["pool_item_id"] == "pool_1"
