from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable
import csv
import json

from backtesting import run_backtest
from backtesting.local_data_provider import split_vt_symbol
from common.time_utils import now_beijing
from data_manager import coverage_service, download_service
from backend.core.hashing import compute_sha256
from backend.domain.enums import ArtifactType, TaskType
from backend.repositories import artifact_repository, pool_repository, run_repository, strategy_repository, variant_repository
from backend.services import artifact_service, task_service


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


def _write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if str(key) not in fieldnames:
                fieldnames.append(str(key))
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)
    temporary.replace(path)


def _persist_rerun_snapshot(
    detail: dict[str, Any],
    *,
    rerun_end: str,
    backtest_result: dict[str, Any],
    curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> None:
    item = dict(detail.get("pool_item") or {})
    pool_item_id = _text(item.get("pool_item_id"))
    pool_path = Path(_text(item.get("pool_path") or detail.get("pool_path")))
    if not pool_item_id or not pool_path.exists():
        raise FileNotFoundError(f"pool snapshot unavailable: {pool_item_id or '-'}")

    result_payload = dict(backtest_result)
    result_payload.pop("daily_results", None)
    result_payload.pop("trades", None)
    config = dict(detail.get("config") or {})
    config.update({"end_date": rerun_end, "last_rerun_at": now_beijing().isoformat(), "last_rerun_end": rerun_end})
    manifest = dict(detail.get("manifest") or {})
    manifest.update({"pool_last_rerun_at": now_beijing().isoformat(), "pool_last_rerun_end": rerun_end})

    result_path = pool_path / "result.json"
    daily_path = pool_path / "daily_results.csv"
    trades_path = pool_path / "trades.csv"
    config_path = pool_path / "config.json"
    manifest_path = pool_path / "manifest.json"
    _write_json_atomic(result_path, result_payload)
    _write_csv_atomic(daily_path, curve)
    _write_csv_atomic(trades_path, trades)
    _write_json_atomic(config_path, config)
    _write_json_atomic(manifest_path, manifest)

    metrics = dict(backtest_result.get("metrics") or {})
    pool_repository.update_pool_item_metrics(
        pool_item_id,
        annual_return=_metric(metrics, "annual_return"),
        max_drawdown=_metric(metrics, "max_drawdown_pct", "max_ddpercent", "max_drawdown"),
        sharpe=_metric(metrics, "sharpe", "sharpe_ratio"),
        calmar=_metric(metrics, "calmar", "return_drawdown_ratio"),
    )
    for artifact_type, path in (
        (ArtifactType.RESULT.value, result_path),
        (ArtifactType.DAILY_RESULTS.value, daily_path),
        (ArtifactType.TRADES.value, trades_path),
        (ArtifactType.CONFIG.value, config_path),
        (ArtifactType.MANIFEST.value, manifest_path),
    ):
        _artifact(pool_item_id, artifact_type, path)


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


def _date_only(value: str | None, default: str = "") -> str:
    text = _text(value, default)
    return text[:10] if len(text) >= 10 else text


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


def _extract_class_name(strategy_code: str) -> str:
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            return node.name
    return ""


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
        "strategy_family": item.get("strategy_family"),
        "strategy_version": item.get("strategy_version"),
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


def _compare_payload_from_parts(detail: dict[str, Any], *, metrics: dict[str, Any], curve: list[dict[str, Any]], trades_rows: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(detail.get("pool_item") or {})
    manifest = dict(detail.get("manifest") or {})
    variant_name = _text(manifest.get("source_variant_name") or manifest.get("variant_name") or item.get("source_variant_id"), "-")
    return {
        "pool_item_id": item.get("pool_item_id"),
        "strategy_id": item.get("strategy_id"),
        "strategy_name": item.get("strategy_name"),
        "strategy_family": item.get("strategy_family"),
        "strategy_version": item.get("strategy_version"),
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


def _rerun_payload(
    detail: dict[str, Any],
    end_date: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    manifest = dict(detail.get("manifest") or {})
    strategy_code = _text(detail.get("strategy_code"))
    if not strategy_code:
        raise FileNotFoundError(f"strategy code not found for pool item: {item.get('pool_item_id')}")
    vt_symbol = _text(item.get("vt_symbol") or config.get("vt_symbol"))
    if not vt_symbol:
        raise ValueError(f"vt_symbol missing for pool item: {item.get('pool_item_id')}")
    symbol, exchange = split_vt_symbol(vt_symbol)
    interval = _text(config.get("interval"), "1m")
    rerun_end = _date_only(end_date, now_beijing().date().isoformat())
    rerun_start = _date_only(config.get("start_date"))
    if not rerun_start:
        local_coverage = coverage_service.get_data_coverage(symbol, exchange, interval)
        rerun_start = _date_only(local_coverage.get("local_start"))
    if not rerun_start or not rerun_end:
        raise ValueError(f"local market data unavailable for {vt_symbol} {interval}")
    requested_coverage = coverage_service.get_data_coverage(
        symbol,
        exchange,
        interval,
        start_date=rerun_start,
        end_date=rerun_end,
    )
    if progress_callback:
        progress_callback(0.12, f"正在检查 {vt_symbol} 行情覆盖")
    if requested_coverage.get("status") != "covered":
        missing_ranges = list(requested_coverage.get("missing_ranges") or [])
        if not missing_ranges:
            missing_ranges = [{"start_date": rerun_start, "end_date": rerun_end}]
        for missing in missing_ranges:
            download_start = _date_only(missing.get("start_date"), rerun_start)
            download_end = _date_only(missing.get("end_date"), rerun_end)
            if not download_start or not download_end or download_start > download_end:
                continue
            if progress_callback:
                progress_callback(0.28, f"正在下载 {vt_symbol} 行情 {download_start} → {download_end}")
            download_result = download_service.download_bars(
                symbol,
                exchange,
                interval,
                download_start,
                download_end,
            )
            if not download_result.get("success"):
                raise RuntimeError(str(download_result.get("error") or f"download failed for {vt_symbol} {download_start} -> {download_end}"))
        requested_coverage = coverage_service.get_data_coverage(
            symbol,
            exchange,
            interval,
            start_date=rerun_start,
            end_date=rerun_end,
        )
        if requested_coverage.get("status") != "covered":
            raise RuntimeError(f"market data still incomplete for {vt_symbol} {interval} {rerun_start} -> {rerun_end}")
    class_name = _text(manifest.get("class_name") or config.get("class_name") or _extract_class_name(strategy_code))
    if not class_name:
        raise ValueError(f"class_name missing for pool item: {item.get('pool_item_id')}")

    if progress_callback:
        progress_callback(0.52, f"行情已就绪，正在回测 {vt_symbol}")
    backtest_result = run_backtest(
        strategy_code=strategy_code,
        class_name=class_name,
        vt_symbol=vt_symbol,
        parameters=_params_from_detail(detail),
        config={
            **config,
            "vt_symbol": vt_symbol,
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": rerun_start,
            "end_date": rerun_end,
            "mode": "real",
        },
    )
    if not backtest_result.get("success"):
        raise RuntimeError(str(backtest_result.get("error") or "pool rerun failed"))

    metrics = dict(backtest_result.get("metrics") or {})
    curve = list(backtest_result.get("daily_results") or [])
    trades_rows = list(backtest_result.get("trades") or [])
    if progress_callback:
        progress_callback(0.86, f"正在保存 {vt_symbol} 最新回测快照")
    _persist_rerun_snapshot(
        detail,
        rerun_end=rerun_end,
        backtest_result=backtest_result,
        curve=curve,
        trades=trades_rows,
    )
    payload = _compare_payload_from_parts(detail, metrics=metrics, curve=curve, trades_rows=trades_rows)
    payload["rerun_end"] = rerun_end
    payload["rerun_start"] = rerun_start
    if progress_callback:
        progress_callback(0.92, f"{vt_symbol} 回测完成，正在整理结果")
    return payload


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
        strategy_family=str(strategy.get("strategy_family") or ""),
        strategy_version=str(strategy.get("strategy_version") or ""),
        vt_symbol=vt_symbol,
        annual_return=_metric(metrics, "annual_return"),
        max_drawdown=_metric(metrics, "max_drawdown_pct", "max_ddpercent", "max_drawdown"),
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


def rerun_pool_items_to_latest(pool_item_ids: list[str] | None, *, end_date: str | None = None) -> dict[str, Any]:
    requested_ids = [_text(item) for item in pool_item_ids or [] if _text(item)]
    requested_end_date = _date_only(end_date, now_beijing().date().isoformat())
    if not requested_ids:
        return {
            "task": None,
            "items": [],
            "benchmark": {"label": "Buy & Hold", "curve": []},
            "diagnostics": [],
            "rerun_end": requested_end_date,
        }

    task = task_service.create_task(
        TaskType.POOL_REBUILD.value,
        message="Pool rerun queued",
        related_pool_item_id=requested_ids[0] if len(requested_ids) == 1 else None,
    )
    task = task_service.mark_running(task["task_id"], message="正在准备策略池重跑")
    diagnostics: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    total_items = len(requested_ids)
    for item_index, pool_item_id in enumerate(requested_ids):
        try:
            detail = get_pool_item_detail(pool_item_id)
        except FileNotFoundError:
            diagnostics.append({"level": "warning", "message": f"pool item not found: {pool_item_id}", "pool_item_id": pool_item_id})
            continue

        try:
            item_start = 0.05 + (item_index / total_items) * 0.85
            item_span = 0.85 / total_items

            def report_item_progress(phase: float, message: str) -> None:
                task_service.mark_progress(task["task_id"], item_start + item_span * phase, message=message)

            items.append(_rerun_payload(detail, end_date=requested_end_date, progress_callback=report_item_progress))
        except Exception as exc:
            diagnostics.append({"level": "warning", "message": f"pool rerun failed: {pool_item_id} | {exc}", "pool_item_id": pool_item_id})

    benchmark_rows: list[dict[str, Any]] = []
    benchmark_diagnostic: dict[str, Any] | None = None
    for item in items:
        benchmark_rows, benchmark_diagnostic = _benchmark_curve(list(item.get("curve") or []))
        if benchmark_rows:
            break
    if benchmark_diagnostic and items:
        diagnostics.append(benchmark_diagnostic)

    if items:
        task_service.mark_progress(task["task_id"], 0.96, message="正在汇总曲线与指标")
        task = task_service.mark_completed(task["task_id"], message="策略池重跑完成")
    else:
        failure_messages = list(dict.fromkeys(
            str(item.get("message") or "").split(" | ", 1)[-1]
            for item in diagnostics
            if item.get("message")
        ))
        detailed_error = "; ".join(failure_messages)[:2000] or "No selected pool items reran successfully"
        task = task_service.mark_failed(task["task_id"], error=detailed_error, message="Pool rerun failed")

    return {
        "task": task,
        "items": items,
        "benchmark": {"label": "Buy & Hold", "curve": benchmark_rows},
        "diagnostics": diagnostics,
        "rerun_end": requested_end_date or _text(items[0].get("rerun_end") if items else ""),
    }
