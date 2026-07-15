from __future__ import annotations

import csv
import json

from backend.services import query_service


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["trade_id", "price"])
        writer.writeheader()
        writer.writerows(rows)


def test_run_detail_reuses_baseline_files_and_streams_other_trade_counts(tmp_path, monkeypatch):
    run_path = tmp_path / "run_1"
    baseline_path = run_path / "variants" / "baseline"
    manual_path = run_path / "variants" / "manual_grid"
    baseline_path.mkdir(parents=True)
    manual_path.mkdir(parents=True)
    (run_path / "manifest.json").write_text("{}", encoding="utf-8")
    (run_path / "input.json").write_text("{}", encoding="utf-8")
    (run_path / "config.json").write_text("{}", encoding="utf-8")
    (run_path / "strategy.py").write_text("class Strategy: pass", encoding="utf-8")
    (baseline_path / "result.json").write_text(json.dumps({"metrics": {"sharpe": 1}}), encoding="utf-8")
    (manual_path / "result.json").write_text(json.dumps({"metrics": {"sharpe": 2}}), encoding="utf-8")
    _write_csv(baseline_path / "trades.csv", [{"trade_id": "1", "price": "10"}])
    _write_csv(
        manual_path / "trades.csv",
        [{"trade_id": str(index), "price": "10"} for index in range(3)],
    )

    variants = [
        {
            "variant_id": "variant_baseline",
            "variant_name": "baseline",
            "result_path": str(baseline_path / "result.json"),
            "trades_path": str(baseline_path / "trades.csv"),
        },
        {
            "variant_id": "variant_manual",
            "variant_name": "manual_grid",
            "result_path": str(manual_path / "result.json"),
            "trades_path": str(manual_path / "trades.csv"),
        },
    ]
    monkeypatch.setattr(query_service.run_repository, "get_run", lambda _run_id: {
        "run_id": "run_1", "strategy_id": "strategy_1", "runtime_path": str(run_path)
    })
    monkeypatch.setattr(query_service.variant_repository, "list_variants", lambda _run_id: variants)
    monkeypatch.setattr(query_service.strategy_repository, "get_strategy", lambda _strategy_id: {"strategy_id": "strategy_1"})
    monkeypatch.setattr(query_service.artifact_repository, "list_artifacts", lambda *_args: [])

    original_read_csv = query_service._read_csv
    fully_read_paths = []

    def tracking_read_csv(path):
        fully_read_paths.append(str(path))
        return original_read_csv(path)

    monkeypatch.setattr(query_service, "_read_csv", tracking_read_csv)

    detail = query_service.get_run_detail("run_1")

    assert detail["baseline_trades_count"] == 1
    assert detail["variant_trade_counts"] == {"baseline": 1, "manual_grid": 3}
    assert detail["variant_results"]["baseline"]["metrics"]["sharpe"] == 1
    assert detail["variant_results"]["manual_grid"]["metrics"]["sharpe"] == 2
    assert fully_read_paths.count(str(baseline_path / "trades.csv")) == 1
    assert str(manual_path / "trades.csv") not in fully_read_paths
