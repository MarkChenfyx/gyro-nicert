from __future__ import annotations

import json
from pathlib import Path

from backend.services import pool_service


def _prepare_snapshot(tmp_path: Path) -> Path:
    pool_path = tmp_path / "pool_item"
    pool_path.mkdir()
    (pool_path / "manifest.json").write_text(json.dumps({"class_name": "ExampleStrategy"}), encoding="utf-8")
    (pool_path / "input.json").write_text("{}", encoding="utf-8")
    (pool_path / "config.json").write_text(json.dumps({"start_date": "2025-01-01"}), encoding="utf-8")
    (pool_path / "strategy.py").write_text("class ExampleStrategy:\n    pass\n", encoding="utf-8")
    (pool_path / "result.json").write_text(json.dumps({"metrics": {"sharpe": 1.0}}), encoding="utf-8")
    (pool_path / "daily_results.csv").write_text("date,net_pnl\n2025-01-01,0\n", encoding="utf-8")
    (pool_path / "trades.csv").write_text("datetime\n", encoding="utf-8")
    return pool_path


def test_add_variant_reruns_from_earliest_local_data(tmp_path, monkeypatch):
    pool_path = _prepare_snapshot(tmp_path)
    pool_item = {
        "pool_item_id": "pool_1",
        "pool_path": str(pool_path),
        "strategy_id": "strategy_1",
        "source_run_id": "run_1",
        "source_variant_id": "variant_1",
        "strategy_name": "Example",
        "vt_symbol": "511380.SSE",
        "sharpe": 1.0,
    }
    rerun_calls: list[tuple[list[str], str | None, str | None]] = []
    snapshot_notes: list[str | None] = []

    monkeypatch.setattr(pool_service.run_repository, "get_run", lambda run_id: {"run_id": run_id, "strategy_id": "strategy_1"})
    monkeypatch.setattr(
        pool_service.variant_repository,
        "get_variant_by_run_and_name",
        lambda run_id, variant_name: {"variant_id": "variant_1", "variant_name": variant_name},
    )
    monkeypatch.setattr(pool_service.strategy_repository, "get_strategy", lambda strategy_id: {"strategy_name": "Example"})
    def fake_create_pool_snapshot(run_id, variant_name, tags=None, note=None):
        snapshot_notes.append(note)
        return {"pool_item_id": "pool_1", "pool_path": pool_path}

    monkeypatch.setattr(pool_service.artifact_service, "create_pool_snapshot", fake_create_pool_snapshot)
    monkeypatch.setattr(pool_service.pool_repository, "create_pool_item", lambda **kwargs: dict(pool_item))
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: {**pool_item, "sharpe": 1.3})
    monkeypatch.setattr(pool_service.artifact_repository, "create_artifact", lambda **kwargs: kwargs)

    def fake_rerun(pool_item_ids, *, end_date=None, start_mode=None):
        rerun_calls.append((pool_item_ids, end_date, start_mode))
        return {
            "items": [{"pool_item_id": "pool_1", "rerun_start": "2023-01-03", "rerun_end": "2026-07-15"}],
            "diagnostics": [],
            "rerun_end": "2026-07-15",
        }

    monkeypatch.setattr(pool_service, "rerun_pool_items_to_latest", fake_rerun)

    result = pool_service.add_variant_to_pool(
        "run_1",
        "manual_grid",
        note="适合震荡行情\n注意回撤",
        vt_symbol="511380.SSE",
        strategy_name="Example manual grid",
    )

    assert rerun_calls == [(["pool_1"], None, "auto_earliest")]
    assert snapshot_notes == ["适合震荡行情\n注意回撤"]
    assert result["rerun_succeeded"] is True
    assert result["rerun"]["items"][0]["rerun_start"] == "2023-01-03"
    assert result["sharpe"] == 1.3


def test_persist_rerun_snapshot_saves_expanded_date_range(tmp_path, monkeypatch):
    pool_path = _prepare_snapshot(tmp_path)
    detail = {
        "pool_item": {"pool_item_id": "pool_1", "pool_path": str(pool_path)},
        "pool_path": str(pool_path),
        "config": {"start_date": "2025-01-01", "parameters": {"window": 10}},
        "manifest": {"class_name": "ExampleStrategy"},
        "result": {"params": {"window": 10}},
    }
    monkeypatch.setattr(pool_service.pool_repository, "update_pool_item_metrics", lambda *args, **kwargs: {})
    monkeypatch.setattr(pool_service, "_artifact", lambda *args, **kwargs: None)

    pool_service._persist_rerun_snapshot(
        detail,
        rerun_start="2023-01-03",
        rerun_end="2026-07-15",
        backtest_result={"metrics": {"sharpe": 1.2}},
        curve=[{"date": "2023-01-03", "net_pnl": 0}],
        trades=[],
    )

    config = json.loads((pool_path / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((pool_path / "manifest.json").read_text(encoding="utf-8"))
    assert config["start_date"] == "2023-01-03"
    assert config["end_date"] == "2026-07-15"
    assert config["last_rerun_start"] == "2023-01-03"
    assert manifest["pool_last_rerun_start"] == "2023-01-03"
    assert manifest["pool_last_rerun_end"] == "2026-07-15"
