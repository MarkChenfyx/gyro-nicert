from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import json

from backend.repositories import artifact_repository, run_repository, strategy_repository, variant_repository
from backend.services import pool_service


def _read_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    return json.loads(candidate.read_text(encoding="utf-8"))


def _read_csv(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"columns": [], "data": []}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {"columns": [], "data": []}
    with candidate.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        columns = list(reader.fieldnames or [])
    return {"columns": columns, "data": rows}


def _count_csv_rows(path: str | Path | None) -> int:
    if not path:
        return 0
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return 0
    with candidate.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _variant_artifact_path(run_path: Path, variant: dict[str, Any], filename: str) -> Path | None:
    explicit = variant.get({
        "result.json": "result_path",
        "daily_results.csv": "daily_results_path",
        "trades.csv": "trades_path",
    }[filename])
    if explicit:
        return Path(str(explicit))
    variant_name = str(variant.get("variant_name") or "").strip()
    if not variant_name:
        return None
    return run_path / "variants" / variant_name / filename


def _latest_variant_payloads(
    run_path: Path,
    variants: list[dict[str, Any]],
    *,
    preloaded_results: dict[str, dict[str, Any]] | None = None,
    preloaded_trade_counts: dict[str, int] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    by_name = dict(preloaded_results or {})
    trade_counts = dict(preloaded_trade_counts or {})
    for variant in reversed(variants):
        variant_name = str(variant.get("variant_name") or "").strip()
        if not variant_name or variant_name in by_name:
            continue
        by_name[variant_name] = _read_json(_variant_artifact_path(run_path, variant, "result.json") or "")
        trade_counts[variant_name] = _count_csv_rows(_variant_artifact_path(run_path, variant, "trades.csv"))
    return by_name, trade_counts


def _latest_variant_grid_summaries(run_path: Path, variants: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        variant_name = str(variant.get("variant_name") or "").strip()
        if not variant_name or variant_name in by_name:
            continue
        grid_summary_path = run_path / "variants" / variant_name / "grid_summary.csv"
        by_name[variant_name] = list(_read_csv(grid_summary_path).get("data") or [])
    return by_name


def get_run_detail(run_id: str) -> dict[str, Any]:
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    run_path = Path(str(run["runtime_path"]))
    variants = variant_repository.list_variants(run_id)
    strategy = strategy_repository.get_strategy(str(run["strategy_id"])) or {}
    baseline_variant = next((variant for variant in variants if str(variant.get("variant_name") or "") == "baseline"), None)
    baseline_result_path = Path(str(baseline_variant.get("result_path"))) if baseline_variant and baseline_variant.get("result_path") else (run_path / "variants" / "baseline" / "result.json")
    baseline_trades_path = Path(str(baseline_variant.get("trades_path"))) if baseline_variant and baseline_variant.get("trades_path") else (run_path / "variants" / "baseline" / "trades.csv")
    baseline_result = _read_json(baseline_result_path)
    baseline_trades = _read_csv(baseline_trades_path)
    baseline_trades_count = len(baseline_trades.get("data") or [])
    variant_results, variant_trade_counts = _latest_variant_payloads(
        run_path,
        variants,
        preloaded_results={"baseline": baseline_result} if baseline_variant else None,
        preloaded_trade_counts={"baseline": baseline_trades_count} if baseline_variant else None,
    )
    variant_grid_summaries = _latest_variant_grid_summaries(run_path, variants)
    return {
        "run": run,
        "strategy": strategy,
        "variants": variants,
        "artifacts": artifact_repository.list_artifacts("run", run_id),
        "variant_artifacts": {
            str(variant["variant_id"]): artifact_repository.list_artifacts("variant", str(variant["variant_id"]))
            for variant in variants
        },
        "manifest": _read_json(run_path / "manifest.json"),
        "input": _read_json(run_path / "input.json"),
        "config": _read_json(run_path / "config.json"),
        "strategy_code": (run_path / "strategy.py").read_text(encoding="utf-8") if (run_path / "strategy.py").exists() else "",
        "baseline_result": baseline_result,
        "baseline_trades": baseline_trades,
        "baseline_trades_count": baseline_trades_count,
        "variant_results": variant_results,
        "variant_trade_counts": variant_trade_counts,
        "variant_grid_summaries": variant_grid_summaries,
    }


def get_variant_curve(run_id: str, variant_name: str) -> dict[str, Any]:
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    run_path = Path(str(run["runtime_path"]))
    return _read_csv(_variant_artifact_path(run_path, variant, "daily_results.csv"))


def get_variant_trades(run_id: str, variant_name: str) -> dict[str, Any]:
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    run_path = Path(str(run["runtime_path"]))
    return _read_csv(_variant_artifact_path(run_path, variant, "trades.csv"))


def get_pool_curve(pool_item_id: str) -> dict[str, Any]:
    detail = pool_service.get_pool_item_detail(pool_item_id)
    return _read_csv(detail.get("daily_results_path"))
