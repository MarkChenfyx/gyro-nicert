from __future__ import annotations

from backend.core.paths import path_fields

from datetime import date
from math import sqrt
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any
from uuid import uuid4
import csv
import hashlib
import json

from backend.common.time_utils import now_iso, timestamp_id
from backend.core.hashing import compute_sha256
from backend.core.paths import PORTFOLIOS_ROOT
from backend.repositories import portfolio_repository, pool_repository


ANNUAL_DAYS = 240
MAX_COMPONENTS = 50


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _date_key(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return text[:10].replace("/", "-")


def _validated_date(value: Any, label: str) -> str:
    resolved = _date_key(value)
    if not resolved:
        return ""
    try:
        date.fromisoformat(resolved)
    except ValueError as exc:
        raise ValueError(f"{label}格式无效：{resolved}") from exc
    return resolved


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(path_fields(payload, storing=True), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if str(key) not in fieldnames:
                fieldnames.append(str(key))
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            if fieldnames:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in fieldnames} for row in rows)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _definition_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portfolio_id() -> str:
    return f"portfolio_{timestamp_id()}_{uuid4().hex[:6]}"


def _snapshot_id() -> str:
    return f"snapshot_{timestamp_id()}_{uuid4().hex[:6]}"


def _close(row: dict[str, Any]) -> float | None:
    for key in ("close_price", "close", "price"):
        value = row.get(key)
        if value not in {None, ""}:
            number = _number(value, float("nan"))
            if number == number and number > 0:
                return number
    return None


def _reference_close(row: dict[str, Any], previous_close: float | None) -> float | None:
    if previous_close is not None and previous_close > 0:
        return previous_close
    current_close = _close(row)
    for key in ("pre_close", "prev_close", "previous_close"):
        candidate = _number(row.get(key), 0.0)
        if candidate > 0 and current_close and 0.5 < candidate / current_close < 1.5:
            return candidate
    return current_close


def _component_daily(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    previous_close: float | None = None
    daily: dict[str, dict[str, float]] = {}
    for row in sorted(rows, key=lambda item: _date_key(item.get("date") or item.get("datetime") or item.get("trading_day"))):
        current_date = _date_key(row.get("date") or row.get("datetime") or row.get("trading_day"))
        if not current_date:
            continue
        current_close = _close(row)
        denominator = _reference_close(row, previous_close)
        if current_close is not None:
            previous_close = current_close
        if denominator is None or denominator <= 0:
            continue
        daily[current_date] = {
            "daily_return": _number(row.get("net_pnl")) / denominator * 100.0,
            "fee_return": _number(row.get("commission")) / denominator * 100.0,
            "turnover_return": _number(row.get("turnover")) / denominator * 100.0,
            "trade_count": _number(row.get("trade_count") or row.get("trades")),
        }
    return daily


def _drawdowns(daily_returns: list[float]) -> tuple[list[float], list[float], float]:
    cumulative = 0.0
    peak = 0.0
    cumulative_values: list[float] = []
    drawdown_values: list[float] = []
    for value in daily_returns:
        cumulative += value
        peak = max(peak, cumulative)
        cumulative_values.append(cumulative)
        drawdown_values.append(min(0.0, cumulative - peak))
    return cumulative_values, drawdown_values, min(drawdown_values or [0.0])


def _validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    name = _text(payload.get("name"))
    if not name:
        raise ValueError("组合名称不能为空")
    if len(name) > 80:
        raise ValueError("组合名称不能超过 80 字")
    description = _text(payload.get("description"))
    if len(description) > 1000:
        raise ValueError("组合说明不能超过 1000 字")
    virtual_capital = _number(payload.get("virtual_capital"), 0.0)
    if virtual_capital <= 0:
        raise ValueError("统计本金必须大于 0")
    raw_components = list(payload.get("components") or [])
    if not raw_components:
        raise ValueError("请至少选择一个子策略")
    if len(raw_components) > MAX_COMPONENTS:
        raise ValueError(f"一个组合最多包含 {MAX_COMPONENTS} 个子策略")
    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_components:
        pool_item_id = _text(item.get("pool_item_id"))
        weight = _number(item.get("weight"), 0.0)
        if not pool_item_id:
            raise ValueError("子策略缺少策略池快照编号")
        if pool_item_id in seen:
            raise ValueError(f"子策略重复：{pool_item_id}")
        if weight <= 0:
            raise ValueError("子策略权重必须大于 0")
        seen.add(pool_item_id)
        components.append({"pool_item_id": pool_item_id, "weight": weight})
    return {
        "name": name,
        "description": description,
        "virtual_capital": virtual_capital,
        "start_date": _validated_date(payload.get("start_date"), "开始日期"),
        "end_date": _validated_date(payload.get("end_date"), "结束日期"),
        "alignment_mode": "cash_fill",
        "components": components,
    }


def calculate_portfolio_definition(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _validate_input(payload)
    component_sources: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    starts: list[str] = []
    ends: list[str] = []

    for item in definition["components"]:
        pool_item_id = item["pool_item_id"]
        pool_item = pool_repository.get_pool_item(pool_item_id)
        if pool_item is None:
            raise FileNotFoundError(f"策略池快照不存在：{pool_item_id}")
        daily_path = Path(_text(pool_item.get("pool_path"))) / "daily_results.csv"
        rows = _read_csv(daily_path)
        daily = _component_daily(rows)
        dates = sorted(daily)
        if not dates:
            raise ValueError(f"策略池快照没有可用日结果：{pool_item_id}")
        starts.append(dates[0])
        ends.append(dates[-1])
        source_hashes[pool_item_id] = compute_sha256(daily_path)
        component_sources.append({
            **item,
            "strategy_name": _text(pool_item.get("strategy_name")) or pool_item_id,
            "strategy_version": _text(pool_item.get("strategy_version")),
            "vt_symbol": _text(pool_item.get("vt_symbol")),
            "source_start_date": dates[0],
            "source_end_date": dates[-1],
            "daily": daily,
        })

    available_start = min(starts)
    available_end = max(ends)
    common_start = max(starts)
    common_end = min(ends)
    start_date = definition["start_date"] or available_start
    end_date = definition["end_date"] or available_end
    if start_date < available_start or end_date > available_end:
        raise ValueError(f"分析区间必须位于已有数据总区间 {available_start} 至 {available_end}")
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")

    calendar = sorted({
        current_date
        for source in component_sources
        for current_date in source["daily"]
        if start_date <= current_date <= end_date
    })
    if not calendar:
        raise ValueError("分析区间内没有可用交易日")

    total_weight = sum(float(item["weight"]) for item in component_sources)
    portfolio_daily_returns: list[float] = []
    portfolio_fee_returns: list[float] = []
    portfolio_turnover_returns: list[float] = []
    portfolio_trade_counts: list[float] = []
    portfolio_active_weights: list[float] = []
    portfolio_cash_weights: list[float] = []
    component_rows: list[dict[str, Any]] = []
    component_summaries: list[dict[str, Any]] = []

    for source in component_sources:
        effective_weight = float(source["weight"]) / total_weight
        own_returns = [source["daily"].get(current_date, {}).get("daily_return", 0.0) for current_date in calendar]
        active_days = sum(1 for current_date in calendar if current_date in source["daily"])
        cash_days = len(calendar) - active_days
        own_cumulative, own_drawdowns, own_max_drawdown = _drawdowns(own_returns)
        component_summaries.append({
            "pool_item_id": source["pool_item_id"],
            "strategy_name": source["strategy_name"],
            "strategy_version": source["strategy_version"],
            "vt_symbol": source["vt_symbol"],
            "weight": source["weight"],
            "effective_weight": effective_weight,
            "source_start_date": source["source_start_date"],
            "source_end_date": source["source_end_date"],
            "active_days": active_days,
            "cash_days": cash_days,
            "cash_ratio": cash_days / len(calendar),
            "total_return": sum(own_returns),
            "weighted_contribution": sum(own_returns) * effective_weight,
            "max_drawdown": own_max_drawdown,
            "trade_count": int(sum(source["daily"].get(current_date, {}).get("trade_count", 0.0) for current_date in calendar)),
            "source_hash": source_hashes[source["pool_item_id"]],
        })
        for index, current_date in enumerate(calendar):
            daily_return = own_returns[index]
            has_data = current_date in source["daily"]
            component_rows.append({
                "date": current_date,
                "pool_item_id": source["pool_item_id"],
                "strategy_name": source["strategy_name"],
                "vt_symbol": source["vt_symbol"],
                "weight": source["weight"],
                "effective_weight": effective_weight,
                "allocation_status": "active" if has_data else "cash",
                "active_weight": effective_weight if has_data else 0.0,
                "cash_weight": 0.0 if has_data else effective_weight,
                "daily_return": daily_return,
                "weighted_contribution": daily_return * effective_weight,
                "cumulative_return": own_cumulative[index],
                "drawdown": own_drawdowns[index],
            })

    for current_date in calendar:
        daily_return = 0.0
        fee_return = 0.0
        turnover_return = 0.0
        trade_count = 0.0
        active_weight = 0.0
        for source in component_sources:
            effective_weight = float(source["weight"]) / total_weight
            values = source["daily"].get(current_date, {})
            if current_date in source["daily"]:
                active_weight += effective_weight
            daily_return += effective_weight * values.get("daily_return", 0.0)
            fee_return += effective_weight * values.get("fee_return", 0.0)
            turnover_return += effective_weight * values.get("turnover_return", 0.0)
            trade_count += values.get("trade_count", 0.0)
        portfolio_daily_returns.append(daily_return)
        portfolio_fee_returns.append(fee_return)
        portfolio_turnover_returns.append(turnover_return)
        portfolio_trade_counts.append(trade_count)
        portfolio_active_weights.append(active_weight)
        portfolio_cash_weights.append(max(0.0, 1.0 - active_weight))

    cumulative, drawdowns, max_drawdown = _drawdowns(portfolio_daily_returns)
    total_return = cumulative[-1]
    deviation = pstdev(portfolio_daily_returns) if len(portfolio_daily_returns) > 1 else 0.0
    sharpe = fmean(portfolio_daily_returns) / deviation * sqrt(ANNUAL_DAYS) if deviation > 0 else 0.0
    annual_return = total_return / len(calendar) * ANNUAL_DAYS
    calmar = total_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    capital = float(definition["virtual_capital"])
    metrics = {
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": calmar,
        "virtual_pnl": capital * total_return / 100.0,
        "average_daily_pnl": capital * fmean(portfolio_daily_returns) / 100.0,
        "total_fee": capital * sum(portfolio_fee_returns) / 100.0,
        "estimated_turnover": capital * sum(portfolio_turnover_returns) / 100.0,
        "trade_count": int(sum(portfolio_trade_counts)),
        "winning_days": sum(1 for value in portfolio_daily_returns if value > 0),
        "losing_days": sum(1 for value in portfolio_daily_returns if value < 0),
        "flat_days": sum(1 for value in portfolio_daily_returns if value == 0),
        "trading_days": len(calendar),
        "daily_return_std": deviation,
        "average_active_weight": fmean(portfolio_active_weights),
        "average_cash_weight": fmean(portfolio_cash_weights),
        "max_cash_weight": max(portfolio_cash_weights),
        "cash_days": sum(1 for value in portfolio_cash_weights if value > 1e-12),
        "fully_invested_days": sum(1 for value in portfolio_cash_weights if value <= 1e-12),
    }
    daily_results = [
        {
            "date": current_date,
            "close_price": 100.0,
            "pre_close": 100.0,
            "net_pnl": portfolio_daily_returns[index],
            "daily_return": portfolio_daily_returns[index],
            "cumulative_return": cumulative[index],
            "drawdown": drawdowns[index],
            "virtual_pnl": capital * cumulative[index] / 100.0,
            "daily_virtual_pnl": capital * portfolio_daily_returns[index] / 100.0,
            "estimated_fee": capital * portfolio_fee_returns[index] / 100.0,
            "trade_count": int(portfolio_trade_counts[index]),
            "active_weight": portfolio_active_weights[index],
            "cash_weight": portfolio_cash_weights[index],
        }
        for index, current_date in enumerate(calendar)
    ]
    resolved_definition = {
        **definition,
        "start_date": start_date,
        "end_date": end_date,
        "available_start_date": available_start,
        "available_end_date": available_end,
        "has_common_interval": common_start <= common_end,
        "common_start_date": common_start if common_start <= common_end else "",
        "common_end_date": common_end if common_start <= common_end else "",
        "components": [
            {"pool_item_id": item["pool_item_id"], "weight": item["weight"]}
            for item in component_sources
        ],
    }
    return {
        "definition": resolved_definition,
        "definition_hash": _definition_hash(resolved_definition),
        "source_hashes": source_hashes,
        "metrics": metrics,
        "components": component_summaries,
        "daily_results": daily_results,
        "component_daily": component_rows,
    }


def _persist_snapshot(portfolio_id: str, calculation: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = _snapshot_id()
    snapshot_path = PORTFOLIOS_ROOT / portfolio_id / snapshot_id
    snapshot_path.mkdir(parents=True, exist_ok=False)
    _write_json(snapshot_path / "definition.json", calculation["definition"])
    _write_json(snapshot_path / "metrics.json", calculation["metrics"])
    _write_json(snapshot_path / "components.json", calculation["components"])
    _write_csv(snapshot_path / "daily_results.csv", calculation["daily_results"])
    _write_csv(snapshot_path / "component_contributions.csv", calculation["component_daily"])
    return portfolio_repository.create_snapshot(
        snapshot_id=snapshot_id,
        portfolio_id=portfolio_id,
        definition_hash=calculation["definition_hash"],
        source_hashes=calculation["source_hashes"],
        metrics=calculation["metrics"],
        artifact_path=str(snapshot_path),
    )


def create_portfolio(payload: dict[str, Any]) -> dict[str, Any]:
    calculation = calculate_portfolio_definition(payload)
    definition = calculation["definition"]
    portfolio_id = _portfolio_id()
    portfolio_repository.create_portfolio(
        portfolio_id=portfolio_id,
        name=definition["name"],
        description=definition["description"],
        virtual_capital=definition["virtual_capital"],
        start_date=definition["start_date"],
        end_date=definition["end_date"],
        alignment_mode=definition["alignment_mode"],
        components=definition["components"],
    )
    _persist_snapshot(portfolio_id, calculation)
    return get_portfolio_detail(portfolio_id)


def update_portfolio(portfolio_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    stored = portfolio_repository.get_portfolio(portfolio_id)
    if stored is None or stored.get("archived_at"):
        raise FileNotFoundError(f"组合不存在或已归档：{portfolio_id}")
    calculation = calculate_portfolio_definition(payload)
    definition = calculation["definition"]
    portfolio_repository.update_portfolio(
        portfolio_id,
        name=definition["name"],
        description=definition["description"],
        virtual_capital=definition["virtual_capital"],
        start_date=definition["start_date"],
        end_date=definition["end_date"],
        alignment_mode=definition["alignment_mode"],
        components=definition["components"],
    )
    _persist_snapshot(portfolio_id, calculation)
    return get_portfolio_detail(portfolio_id)


def refresh_portfolio(portfolio_id: str) -> dict[str, Any]:
    stored = portfolio_repository.get_portfolio(portfolio_id)
    if stored is None or stored.get("archived_at"):
        raise FileNotFoundError(f"组合不存在或已归档：{portfolio_id}")
    payload = {
        "name": stored["name"],
        "description": stored.get("description") or "",
        "virtual_capital": stored["virtual_capital"],
        "start_date": stored["start_date"],
        "end_date": stored["end_date"],
        "components": stored.get("components") or [],
    }
    calculation = calculate_portfolio_definition(payload)
    _persist_snapshot(portfolio_id, calculation)
    return get_portfolio_detail(portfolio_id)


def _snapshot_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    path = Path(_text(snapshot.get("artifact_path")))
    components_path = path / "components.json"
    metrics_path = path / "metrics.json"
    definition_path = path / "definition.json"
    return {
        **snapshot,
        "definition": json.loads(definition_path.read_text(encoding="utf-8")) if definition_path.exists() else {},
        "metrics": json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else snapshot.get("metrics") or {},
        "components": json.loads(components_path.read_text(encoding="utf-8")) if components_path.exists() else [],
        "daily_results": _read_csv(path / "daily_results.csv"),
        "component_daily": _read_csv(path / "component_contributions.csv"),
    }


def _stale_sources(snapshot: dict[str, Any] | None) -> list[str]:
    if not snapshot:
        return []
    stale: list[str] = []
    for pool_item_id, saved_hash in dict(snapshot.get("source_hashes") or {}).items():
        item = pool_repository.get_pool_item(pool_item_id)
        if item is None:
            stale.append(pool_item_id)
            continue
        daily_path = Path(_text(item.get("pool_path"))) / "daily_results.csv"
        current_hash = compute_sha256(daily_path) if daily_path.exists() else ""
        if current_hash != saved_hash:
            stale.append(pool_item_id)
    return stale


def get_portfolio_detail(portfolio_id: str) -> dict[str, Any]:
    portfolio = portfolio_repository.get_portfolio(portfolio_id)
    if portfolio is None:
        raise FileNotFoundError(f"组合不存在：{portfolio_id}")
    snapshot = portfolio_repository.get_latest_snapshot(portfolio_id)
    return {
        "portfolio": portfolio,
        "snapshot": _snapshot_payload(snapshot),
        "stale_pool_item_ids": _stale_sources(snapshot),
    }


def list_portfolios(*, include_archived: bool = False) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in portfolio_repository.list_portfolios(include_archived=include_archived):
        snapshot = portfolio_repository.get_snapshot(_text(item.get("latest_snapshot_id"))) if item.get("latest_snapshot_id") else None
        result.append({
            **item,
            "metrics": dict((snapshot or {}).get("metrics") or {}),
            "stale_source_count": len(_stale_sources(snapshot)),
        })
    return result


def archive_portfolio(portfolio_id: str) -> dict[str, Any]:
    return portfolio_repository.archive_portfolio(portfolio_id)


def portfolio_export_path(portfolio_id: str) -> Path:
    detail = get_portfolio_detail(portfolio_id)
    snapshot = detail.get("snapshot") or {}
    path = Path(_text(snapshot.get("artifact_path"))) / "daily_results.csv"
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"组合净值数据不存在：{portfolio_id}")
    try:
        path.resolve().relative_to(PORTFOLIOS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("组合导出路径不安全") from exc
    return path
