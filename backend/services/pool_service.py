from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import json

from backend.core.hashing import compute_sha256
from backend.domain.enums import ArtifactType
from backend.repositories import artifact_repository, pool_repository, run_repository, strategy_repository, variant_repository
from backend.services import artifact_service


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"columns": [], "data": []}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        columns = list(reader.fieldnames or [])
    return {"columns": columns, "data": rows}


def _artifact(owner_id: str, artifact_type: str, path: Path | None) -> None:
    if path is None:
        return
    if path.exists() and path.is_file():
        artifact_repository.create_artifact(
            owner_type="pool_item",
            owner_id=owner_id,
            artifact_type=artifact_type,
            path=str(path),
            sha256=compute_sha256(path),
        )


def _metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _tags_from_detail(detail: dict[str, Any]) -> list[str]:
    tags = detail.get("tags")
    if isinstance(tags, list):
        return [str(item) for item in tags]
    if isinstance(tags, dict) and isinstance(tags.get("tags"), list):
        return [str(item) for item in tags["tags"]]
    raw = detail.get("pool_item", {}).get("tags")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [raw]
    return []


def _params_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    config = dict(detail.get("config") or {})
    manifest = dict(detail.get("manifest") or {})
    result = dict(detail.get("result") or {})
    for candidate in (
        config.get("parameters"),
        manifest.get("parameters"),
        result.get("params"),
        result.get("parameters"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def _date_from_row(row: dict[str, Any]) -> str:
    return _text(row.get("date") or row.get("datetime") or row.get("trading_day"))


def _float_from_row(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = row.get(name)
        if value in {None, ""}:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _benchmark_curve(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    base: float | None = None
    curve: list[dict[str, Any]] = []
    for row in rows:
        close = _float_from_row(row, "close_price", "close", "price")
        if close is None:
            continue
        if base in {None, 0}:
            base = close
        if not base:
            continue
        curve.append({"date": _date_from_row(row), "value": (close / base - 1.0) * 100.0})
    if curve:
        return curve, None
    return [], {"level": "warning", "message": "benchmark curve unavailable: selected pool curves do not contain close_price/close/price"}


def _compare_item(detail: dict[str, Any]) -> dict[str, Any]:
    item = dict(detail.get("pool_item") or {})
    manifest = dict(detail.get("manifest") or {})
    result = dict(detail.get("result") or {})
    metrics = dict(result.get("metrics") or result)
    daily = dict(detail.get("daily_results") or {})
    trades = dict(detail.get("trades") or {})
    curve = list(daily.get("data") or [])
    trades_rows = list(trades.get("data") or [])
    variant_name = _text(manifest.get("source_variant_name") or manifest.get("variant_name") or item.get("source_variant_id"), "-")
    return {
        "pool_item_id": item.get("pool_item_id"),
        "strategy_id": item.get("strategy_id"),
        "strategy_name": item.get("strategy_name"),
        "vt_symbol": item.get("vt_symbol"),
        "variant_name": variant_name,
        "created_at": item.get("created_at"),
        "source_run_id": item.get("source_run_id"),
        "metrics": metrics,
        "params": _params_from_detail(detail),
        "tags": _tags_from_detail(detail),
        "notes": detail.get("notes") or "",
        "curve": curve,
        "trades_preview": trades_rows[:20],
    }


def add_variant_to_pool(
    run_id: str,
    variant_name: str,
    tags: list[str] | None = None,
    note: str | None = None,
    vt_symbol: str | None = None,
) -> dict[str, Any]:
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")

    snapshot = artifact_service.create_pool_snapshot(run_id, variant_name, tags=tags, note=note)
    pool_item_id = str(snapshot["pool_item_id"])
    pool_path = Path(snapshot["pool_path"])
    result = _read_json(pool_path / "result.json")
    metrics = dict(result.get("metrics") or result)
    strategy = strategy_repository.get_strategy(str(run["strategy_id"])) or {}
    strategy_name = str(strategy.get("strategy_name") or run.get("strategy_id") or "")

    pool_item = pool_repository.create_pool_item(
        pool_item_id=pool_item_id,
        strategy_id=str(run["strategy_id"]),
        source_run_id=run_id,
        source_variant_id=str(variant["variant_id"]),
        pool_path=str(pool_path),
        strategy_name=strategy_name,
        vt_symbol=vt_symbol,
        annual_return=_metric(metrics, "annual_return"),
        max_drawdown=_metric(metrics, "max_drawdown", "max_ddpercent"),
        sharpe=_metric(metrics, "sharpe", "sharpe_ratio"),
        calmar=_metric(metrics, "calmar", "return_drawdown_ratio"),
        tags=tags,
    )

    _artifact(pool_item_id, ArtifactType.MANIFEST.value, pool_path / "manifest.json")
    _artifact(pool_item_id, ArtifactType.INPUT.value, pool_path / "input.json")
    _artifact(pool_item_id, ArtifactType.CONFIG.value, pool_path / "config.json")
    _artifact(pool_item_id, ArtifactType.STRATEGY_CODE.value, pool_path / "strategy.py")
    _artifact(pool_item_id, ArtifactType.RESULT.value, pool_path / "result.json")
    _artifact(pool_item_id, ArtifactType.DAILY_RESULTS.value, pool_path / "daily_results.csv")
    _artifact(pool_item_id, ArtifactType.TRADES.value, pool_path / "trades.csv")
    artifact_repository.create_artifact(
        owner_type="pool_item",
        owner_id=pool_item_id,
        artifact_type=ArtifactType.POOL_SNAPSHOT.value,
        path=str(pool_path),
        sha256=None,
    )
    return pool_item


def get_pool_item_detail(pool_item_id: str) -> dict[str, Any]:
    item = pool_repository.get_pool_item(pool_item_id)
    if item is None:
        raise FileNotFoundError(f"Pool item not found: {pool_item_id}")
    pool_path = Path(str(item["pool_path"]))
    detail = {
        "pool_item": item,
        "pool_path": str(pool_path),
        "manifest": _read_json(pool_path / "manifest.json"),
        "config": _read_json(pool_path / "config.json"),
        "result": _read_json(pool_path / "result.json"),
        "tags": _read_json(pool_path / "tags.json"),
        "notes": (pool_path / "notes.md").read_text(encoding="utf-8") if (pool_path / "notes.md").exists() else "",
        "strategy_path": str(pool_path / "strategy.py") if (pool_path / "strategy.py").exists() else "",
        "strategy_code": (pool_path / "strategy.py").read_text(encoding="utf-8") if (pool_path / "strategy.py").exists() else "",
    }
    if (pool_path / "daily_results.csv").exists():
        detail["daily_results_path"] = str(pool_path / "daily_results.csv")
        detail["daily_results"] = _read_csv(pool_path / "daily_results.csv")
    if (pool_path / "trades.csv").exists():
        detail["trades_path"] = str(pool_path / "trades.csv")
        detail["trades"] = _read_csv(pool_path / "trades.csv")
    return detail


def list_pool_items(
    keyword: str | None = None,
    vt_symbol: str | None = None,
    min_sharpe: float | None = None,
    tag: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = 100,
) -> list[dict[str, Any]]:
    return pool_repository.list_pool_items(
        keyword=keyword,
        vt_symbol=vt_symbol,
        min_sharpe=min_sharpe,
        tag=tag,
        sort_by=sort_by,
        order=order,
        limit=limit,
    )


def compare_pool_items(pool_item_ids: list[str] | None) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw_id in pool_item_ids or []:
        pool_item_id = _text(raw_id)
        if not pool_item_id or pool_item_id in seen:
            continue
        seen.add(pool_item_id)
        try:
            detail = get_pool_item_detail(pool_item_id)
        except FileNotFoundError:
            diagnostics.append({"level": "warning", "message": f"pool item not found: {pool_item_id}", "pool_item_id": pool_item_id})
            continue
        payload = _compare_item(detail)
        if not payload["curve"]:
            diagnostics.append({"level": "warning", "message": "pool item has no daily curve", "pool_item_id": pool_item_id})
        items.append(payload)

    benchmark_rows: list[dict[str, Any]] = []
    benchmark_diagnostic: dict[str, Any] | None = None
    for item in items:
        benchmark_rows, benchmark_diagnostic = _benchmark_curve(list(item.get("curve") or []))
        if benchmark_rows:
            break
    if benchmark_diagnostic and items:
        diagnostics.append(benchmark_diagnostic)

    return {
        "items": items,
        "benchmark": {"label": "Buy & Hold", "curve": benchmark_rows},
        "diagnostics": diagnostics,
    }
