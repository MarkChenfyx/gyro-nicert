from __future__ import annotations

from pathlib import Path
import csv
import json

import pytest

from backend.services import optimization_curve_snapshot_service as service


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_curve_snapshot_survives_source_overwrite_and_can_be_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_path = tmp_path / "runs" / "run_test"
    curve_path = run_path / "variants" / "manual_grid" / "daily_results.csv"
    result_path = run_path / "variants" / "manual_grid" / "result.json"
    _write_csv(
        curve_path,
        [
            {"date": "2026-01-02", "close_price": 10, "pre_close": 9.9, "net_pnl": 0.1, "trades": "large payload"},
            {"date": "2026-01-05", "close_price": 10.2, "pre_close": 10, "net_pnl": 0.2, "trades": "large payload"},
        ],
    )
    result_path.write_text(
        json.dumps(
            {
                "objective": "sharpe",
                "recommended": {
                    "parameters": {"lookback_window": 20},
                    "metrics": {"sharpe": 1.2, "strategy_return": 8.5},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "OPTIMIZATION_CURVE_SNAPSHOTS_ROOT", tmp_path / "snapshots")
    monkeypatch.setattr(
        service.run_repository,
        "get_run",
        lambda run_id: {"run_id": run_id, "runtime_path": str(run_path), "strategy_name": "Han123", "vt_symbol": "511380.SSE"},
    )
    monkeypatch.setattr(
        service.variant_repository,
        "get_variant_by_run_and_name",
        lambda run_id, variant_name: {
            "daily_results_path": str(curve_path),
            "result_path": str(result_path),
        },
    )

    created = service.create_curve_snapshot("run_test", "manual_grid", "第一次优化")
    assert created["name"] == "第一次优化"
    assert created["parameters"] == {"lookback_window": 20}
    assert created["curve"] == [
        {"date": "2026-01-02", "close_price": "10", "pre_close": "9.9", "net_pnl": "0.1"},
        {"date": "2026-01-05", "close_price": "10.2", "pre_close": "10", "net_pnl": "0.2"},
    ]

    _write_csv(
        curve_path,
        [{"date": "2026-01-02", "close_price": 10, "pre_close": 9.9, "net_pnl": -9, "trades": "overwritten"}],
    )
    listed = service.list_curve_snapshots()
    assert listed[0]["curve"] == created["curve"]

    renamed = service.rename_curve_snapshot(created["snapshot_id"], "对照曲线")
    assert renamed["name"] == "对照曲线"

    service.delete_curve_snapshot(created["snapshot_id"])
    assert service.list_curve_snapshots() == []


def test_curve_snapshot_rejects_invalid_identifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service, "OPTIMIZATION_CURVE_SNAPSHOTS_ROOT", tmp_path / "snapshots")
    with pytest.raises(ValueError, match="Invalid curve snapshot id"):
        service.delete_curve_snapshot("../outside")
