from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
import csv
import json

from backtesting import run_backtest
from backtesting.local_data_provider import split_vt_symbol
from common.time_utils import now_beijing
from data_manager import coverage_service, download_service
from backend.core.hashing import compute_sha256
from backend.core.paths import POOL_STRATEGIES_ROOT
from backend.domain.enums import ArtifactType, TaskType
from backend.repositories import artifact_repository, pool_repository, run_repository, strategy_repository, variant_repository
from backend.services import artifact_service, run_service, task_service


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
    rerun_start: str,
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
    resolved_params = _params_from_detail(detail)
    if resolved_params:
        result_payload["params"] = resolved_params
    config = dict(detail.get("config") or {})
    if resolved_params:
        config["parameters"] = resolved_params
    config.update({
        "start_date": rerun_start,
        "end_date": rerun_end,
        "last_rerun_at": now_beijing().isoformat(),
        "last_rerun_start": rerun_start,
        "last_rerun_end": rerun_end,
    })
    manifest = dict(detail.get("manifest") or {})
    manifest.update({
        "pool_last_rerun_at": now_beijing().isoformat(),
        "pool_last_rerun_start": rerun_start,
        "pool_last_rerun_end": rerun_end,
    })

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


def _pool_name_prefix(value: Any, default: str = "") -> str:
    resolved = _text(value, default)
    return resolved.split("|", 1)[0].strip()


def _pool_version(item: dict[str, Any], manifest: dict[str, Any] | None = None) -> str:
    explicit = _text(dict(manifest or {}).get("pool_version"))
    if explicit:
        return explicit
    item_id = _text(item.get("pool_item_id"))
    strategy_version = _text(item.get("strategy_version"))
    if strategy_version and item_id == f"pool_{strategy_version}":
        return strategy_version
    return ""


def _pool_item_view(item: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = dict(item)
    pool_version = _pool_version(resolved, manifest)
    if not pool_version:
        return {**resolved, "pool_strategy_name": resolved.get("strategy_name")}
    name_prefix = _pool_name_prefix(resolved.get("strategy_name"), resolved.get("strategy_family") or "策略")
    return {
        **resolved,
        "strategy_name": name_prefix,
        "pool_strategy_name": name_prefix,
        "strategy_version": pool_version,
        "pool_version": pool_version,
        "display_name": f"{name_prefix} | {pool_version}",
        "source_strategy_version": _text(dict(manifest or {}).get("source_strategy_version")),
    }


def _validated_note(note: str | None) -> str:
    text = str(note or "")
    if len(text) > 500:
        raise ValueError("策略池备注不能超过 500 字")
    return text


def _validated_pool_snapshot_path(item: dict[str, Any]) -> Path:
    pool_item_id = _text(item.get("pool_item_id"))
    root = POOL_STRATEGIES_ROOT.resolve()
    candidate = Path(str(item.get("pool_path") or "")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("策略池存储路径不安全，拒绝修改备注") from exc
    if candidate == root:
        raise ValueError("策略池存储路径不安全，拒绝修改备注")
    if not candidate.exists() or not candidate.is_dir():
        raise FileNotFoundError(f"策略池快照目录不存在：{pool_item_id or '-'}")
    return candidate


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
        result.get("recommended", {}).get("parameters") if isinstance(result.get("recommended"), dict) else None,
        result.get("params"),
        result.get("parameters"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
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
        "pool_strategy_name": item.get("strategy_name") or manifest.get("pool_strategy_name"),
        "strategy_family": item.get("strategy_family"),
        "strategy_version": item.get("strategy_version"),
        "pool_version": item.get("pool_version"),
        "display_name": item.get("display_name"),
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
        "trade_count": len(trades_rows),
    }


def _compare_payload_from_parts(detail: dict[str, Any], *, metrics: dict[str, Any], curve: list[dict[str, Any]], trades_rows: list[dict[str, Any]]) -> dict[str, Any]:
    item = dict(detail.get("pool_item") or {})
    manifest = dict(detail.get("manifest") or {})
    variant_name = _text(manifest.get("source_variant_name") or manifest.get("variant_name") or item.get("source_variant_id"), "-")
    return {
        "pool_item_id": item.get("pool_item_id"),
        "strategy_id": item.get("strategy_id"),
        "strategy_name": item.get("strategy_name"),
        "pool_strategy_name": item.get("strategy_name") or manifest.get("pool_strategy_name"),
        "strategy_family": item.get("strategy_family"),
        "strategy_version": item.get("strategy_version"),
        "pool_version": item.get("pool_version"),
        "display_name": item.get("display_name"),
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
        "trade_count": len(trades_rows),
    }


def _rerun_payload(
    detail: dict[str, Any],
    start_date: str | None = None,
    end_date: str | None = None,
    start_mode: str | None = None,
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
    local_coverage = coverage_service.get_data_coverage(symbol, exchange, interval)
    requested_start = _date_only(start_date)
    if requested_start:
        try:
            date.fromisoformat(requested_start)
        except ValueError as exc:
            raise ValueError(f"重跑开始日期格式无效：{requested_start}") from exc
        rerun_start = requested_start
    else:
        normalized_start_mode = _text(start_mode, "saved") or "saved"
        if normalized_start_mode == "auto_earliest":
            rerun_start = _date_only(local_coverage.get("local_start")) or _date_only(config.get("start_date"))
        else:
            rerun_start = _date_only(config.get("start_date")) or _date_only(local_coverage.get("local_start"))
    if not rerun_start:
        raise ValueError(f"local market data unavailable for {vt_symbol} {interval}")
    if rerun_start > rerun_end:
        raise ValueError(f"重跑开始日期不能晚于结束日期：{rerun_start} > {rerun_end}")
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
        rerun_start=rerun_start,
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
    strategy_name: str | None = None,
) -> dict[str, Any]:
    resolved_note = _validated_note(note)
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")

    snapshot = artifact_service.create_pool_snapshot(run_id, variant_name, tags=tags, note=resolved_note)
    pool_item_id = str(snapshot["pool_item_id"])
    pool_path = Path(snapshot["pool_path"])
    result = _read_json(pool_path / "result.json")
    metrics = dict(result.get("metrics") or result)
    strategy = strategy_repository.get_strategy(str(run["strategy_id"])) or {}
    resolved_strategy_name = _pool_name_prefix(
        strategy_name,
        _pool_name_prefix(strategy.get("strategy_name"), run.get("strategy_id") or "策略"),
    )
    pool_version = _text(snapshot.get("pool_version"))
    manifest_path = pool_path / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["pool_strategy_name"] = resolved_strategy_name
    manifest["strategy_name"] = f"{resolved_strategy_name} | {pool_version}"
    _write_json_atomic(manifest_path, manifest)

    pool_item = pool_repository.create_pool_item(
        pool_item_id=pool_item_id,
        strategy_id=str(run["strategy_id"]),
        source_run_id=run_id,
        source_variant_id=str(variant["variant_id"]),
        pool_path=str(pool_path),
        strategy_name=resolved_strategy_name,
        strategy_family=str(strategy.get("strategy_family") or ""),
        strategy_version=pool_version,
        vt_symbol=vt_symbol,
        annual_return=_metric(metrics, "annual_return"),
        max_drawdown=_metric(metrics, "max_drawdown_pct", "max_ddpercent", "max_drawdown"),
        sharpe=_metric(metrics, "sharpe", "sharpe_ratio"),
        calmar=_metric(metrics, "calmar", "return_drawdown_ratio"),
        tags=tags,
        created_at=_text(snapshot.get("created_at")) or None,
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
    try:
        rerun = rerun_pool_items_to_latest([pool_item_id], start_mode="auto_earliest")
    except Exception as exc:
        rerun = {
            "task": None,
            "items": [],
            "benchmark": {"label": "Buy & Hold", "curve": []},
            "diagnostics": [{
                "level": "warning",
                "message": f"pool rerun failed after add: {pool_item_id} | {exc}",
                "pool_item_id": pool_item_id,
            }],
            "rerun_end": "",
        }
    refreshed_pool_item = pool_repository.get_pool_item(pool_item_id) or pool_item
    return {
        **_pool_item_view(dict(refreshed_pool_item), manifest),
        "rerun": rerun,
        "rerun_succeeded": bool(rerun.get("items")),
    }


def get_pool_item_detail(pool_item_id: str) -> dict[str, Any]:
    stored_item = pool_repository.get_pool_item(pool_item_id)
    if stored_item is None:
        raise FileNotFoundError(f"Pool item not found: {pool_item_id}")
    pool_path = Path(str(stored_item["pool_path"]))
    manifest_path = pool_path / "manifest.json"
    manifest = _read_json(manifest_path)
    pool_strategy_name = _text(stored_item.get("strategy_name"))
    if pool_strategy_name and manifest.get("pool_strategy_name") != pool_strategy_name:
        manifest["pool_strategy_name"] = pool_strategy_name
        _write_json_atomic(manifest_path, manifest)
    item = _pool_item_view(dict(stored_item), manifest)
    detail = {
        "pool_item": item,
        "pool_path": str(pool_path),
        "manifest": manifest,
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


def update_pool_item_notes(pool_item_id: str, note: str | None) -> dict[str, Any]:
    item = pool_repository.get_pool_item(pool_item_id)
    if item is None:
        raise FileNotFoundError(f"策略池条目不存在：{pool_item_id}")
    resolved_note = _validated_note(note)
    pool_path = _validated_pool_snapshot_path(dict(item))
    notes_path = (pool_path / "notes.md").resolve()
    try:
        notes_path.relative_to(POOL_STRATEGIES_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("策略池备注路径不安全，拒绝保存") from exc
    temporary = notes_path.with_name(f".{notes_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(resolved_note, encoding="utf-8")
        temporary.replace(notes_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "pool_item_id": pool_item_id,
        "note": resolved_note,
    }


def continue_optimization_from_pool(pool_item_id: str) -> dict[str, Any]:
    """Rerun a stable pool snapshot as a fresh baseline-only optimization run."""
    detail = get_pool_item_detail(pool_item_id)
    item = dict(detail.get("pool_item") or {})
    config = dict(detail.get("config") or {})
    manifest = dict(detail.get("manifest") or {})
    strategy_code = str(detail.get("strategy_code") or "")
    if not strategy_code.strip():
        raise FileNotFoundError(f"strategy code not found for pool item: {pool_item_id}")

    strategy_id = _text(item.get("strategy_id"))
    strategy = strategy_repository.get_strategy(strategy_id) if strategy_id else None
    if strategy is None:
        raise FileNotFoundError(f"strategy record not found for pool item: {pool_item_id}")

    vt_symbol = _text(item.get("vt_symbol") or config.get("vt_symbol"))
    if not vt_symbol:
        raise ValueError(f"vt_symbol missing for pool item: {pool_item_id}")
    symbol, exchange = split_vt_symbol(vt_symbol)
    interval = _text(config.get("interval"), "1m")
    class_name = _text(manifest.get("class_name") or config.get("class_name") or strategy.get("class_name") or _extract_class_name(strategy_code))
    if not class_name:
        raise ValueError(f"class_name missing for pool item: {pool_item_id}")

    parameters = _params_from_detail(detail)
    backtest_config = {
        **config,
        "vt_symbol": vt_symbol,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "mode": "real",
        "execution_mode": "real_backtest",
        "is_real_backtest": True,
        "parameters": parameters,
    }
    backtest_result = run_backtest(
        strategy_code=strategy_code,
        class_name=class_name,
        vt_symbol=vt_symbol,
        parameters=parameters,
        config=backtest_config,
    )
    if not backtest_result.get("success"):
        raise RuntimeError(str(backtest_result.get("error") or "pool baseline rerun failed"))

    original_variant = _text(
        manifest.get("source_variant_name") or manifest.get("variant_name") or item.get("source_variant_id"),
        "baseline",
    )
    source_pool_version = _pool_version(item, manifest) or (pool_item_id[5:] if pool_item_id.startswith("pool_") else "")
    lineage = {
        "source_type": "pool_item",
        "source_pool_item_id": pool_item_id,
        "source_pool_version": source_pool_version,
        "source_strategy_version": _text(manifest.get("source_strategy_version") or item.get("source_strategy_version") or item.get("strategy_version")),
        "source_variant": original_variant,
        "operation": "rerun_as_baseline",
    }
    result_payload = dict(backtest_result)
    result_payload.pop("daily_results", None)
    result_payload.pop("trades", None)
    result_payload["params"] = parameters
    pool_path = Path(str(detail.get("pool_path") or item.get("pool_path") or ""))
    input_payload = _read_json(pool_path / "input.json") if pool_path else {}
    baseline = run_service.create_baseline_run(
        strategy=dict(strategy),
        source_text=_text(input_payload.get("source_text") or strategy.get("source_text") or strategy_code),
        config_payload=backtest_config,
        strategy_code=strategy_code,
        result_payload=result_payload,
        daily_results=backtest_result.get("daily_results"),
        trades=backtest_result.get("trades"),
        manifest_lineage=lineage,
        related_pool_item_id=pool_item_id,
    )
    return {
        "baseline": baseline,
        "lineage": lineage,
        "parameters": parameters,
        "backtest": {
            "success": True,
            "metrics": dict(backtest_result.get("metrics") or {}),
        },
    }


def list_pool_items(
    keyword: str | None = None,
    vt_symbol: str | None = None,
    min_sharpe: float | None = None,
    tag: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = 100,
) -> list[dict[str, Any]]:
    items = pool_repository.list_pool_items(
        keyword=keyword,
        vt_symbol=vt_symbol,
        min_sharpe=min_sharpe,
        tag=tag,
        sort_by=sort_by,
        order=order,
        limit=limit,
    )
    return [_pool_item_view(dict(item)) for item in items]


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


def rerun_pool_items_to_latest(
    pool_item_ids: list[str] | None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    start_mode: str | None = None,
) -> dict[str, Any]:
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

            items.append(_rerun_payload(
                detail,
                start_date=start_date,
                end_date=requested_end_date,
                start_mode=start_mode,
                progress_callback=report_item_progress,
            ))
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
        "rerun_start": _date_only(start_date) or _text(items[0].get("rerun_start") if items else ""),
        "rerun_end": requested_end_date or _text(items[0].get("rerun_end") if items else ""),
    }


def remove_pool_item(pool_item_id: str) -> dict[str, Any]:
    import shutil

    item = pool_repository.get_pool_item(pool_item_id)
    if item is None:
        raise FileNotFoundError(f"Pool item not found: {pool_item_id}")
    pool_path = Path(str(item.get("pool_path") or ""))
    artifact_repository.delete_artifacts_by_owner("pool_item", pool_item_id)
    if pool_path.exists() and pool_path.is_dir():
        shutil.rmtree(pool_path, ignore_errors=True)
    deleted = pool_repository.delete_pool_item(pool_item_id)
    if not deleted:
        raise RuntimeError(f"Failed to delete pool item: {pool_item_id}")
    return {"deleted": True, "pool_item_id": pool_item_id}
