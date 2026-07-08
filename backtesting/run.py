from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import uuid4
import types

from backtesting import local_data_provider
from data_manager import coverage_service

ENGINE_NAME = "vnpy_cta_backtesting_engine"
ENGINE_VERSION = "phase5b_real_v1"


def _diagnostic(level: str, message: str) -> dict[str, str]:
    return {"level": level, "message": message}


def _mock_result(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "metrics": {
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "calmar": 0.0,
        },
        "daily_results": [
            {"date": "1970-01-01", "balance": float(config.get("capital") or 100000.0), "close_price": 1.0}
        ],
        "trades": [],
        "logs": ["mock backtest completed"],
        "diagnostics": [_diagnostic("info", "mock mode returned deterministic backtest result")],
        "engine_name": "mock_backtesting_engine",
        "engine_version": "phase3_5_boundary_v1",
        "error": None,
    }


def _failure(error: str, diagnostics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "metrics": {},
        "daily_results": [],
        "trades": [],
        "logs": [],
        "diagnostics": diagnostics or [_diagnostic("error", error)],
        "engine_name": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "error": error,
    }


def _parse_datetime(value: Any, fallback: str | None = None) -> datetime:
    text = str(value or fallback or "").strip()
    if not text:
        raise ValueError("missing backtest datetime")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text[:10] + "T00:00:00")


def _is_date_only(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _interval_value(interval: str) -> str:
    normalized = str(interval or "1m").lower()
    if normalized in {"1m", "1min", "minute"}:
        return "1m"
    if normalized in {"1d", "d", "day", "daily"}:
        return "1d"
    if normalized in {"1h", "60m", "hour"}:
        return "1h"
    raise ValueError(f"Unsupported interval: {interval}")


def _vnpy_interval(interval: str):
    from vnpy.trader.constant import Interval

    normalized = _interval_value(interval)
    if normalized == "1m":
        return Interval.MINUTE
    if normalized == "1d":
        return Interval.DAILY
    if normalized == "1h":
        return Interval.HOUR
    raise ValueError(f"Unsupported interval: {interval}")


def _load_strategy_class(strategy_code: str, class_name: str):
    from vnpy_ctastrategy import CtaTemplate

    module = types.ModuleType(f"gyro_backtest_strategy_{uuid4().hex}")
    exec(compile(strategy_code, f"<{module.__name__}>", "exec"), module.__dict__)
    strategy_class = getattr(module, class_name, None)
    if strategy_class is None:
        raise ValueError(f"Strategy class not found: {class_name}")
    if not issubclass(strategy_class, CtaTemplate):
        raise ValueError(f"Strategy class must inherit vnpy_ctastrategy.CtaTemplate: {class_name}")
    return strategy_class


def _records_from_daily_df(daily_df: Any) -> list[dict[str, Any]]:
    if daily_df is None:
        return []
    frame = daily_df.reset_index()
    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if hasattr(value, "isoformat"):
                clean[str(key)] = value.isoformat()
            else:
                clean[str(key)] = value
        records.append(clean)
    return records


def _trade_records(trades: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for trade in trades:
        records.append(
            {
                "tradeid": getattr(trade, "tradeid", ""),
                "orderid": getattr(trade, "orderid", ""),
                "symbol": getattr(trade, "symbol", ""),
                "exchange": getattr(getattr(trade, "exchange", ""), "value", getattr(trade, "exchange", "")),
                "direction": getattr(getattr(trade, "direction", ""), "value", getattr(trade, "direction", "")),
                "offset": getattr(getattr(trade, "offset", ""), "value", getattr(trade, "offset", "")),
                "price": getattr(trade, "price", 0),
                "volume": getattr(trade, "volume", 0),
                "datetime": getattr(trade, "datetime", "").isoformat() if hasattr(getattr(trade, "datetime", ""), "isoformat") else str(getattr(trade, "datetime", "")),
            }
        )
    return records


def _metric_aliases(statistics: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(statistics or {})
    metrics["annual_return"] = metrics.get("annual_return", 0)
    metrics["max_drawdown"] = metrics.get("max_drawdown", metrics.get("max_ddpercent", 0))
    metrics["sharpe"] = metrics.get("sharpe_ratio", metrics.get("sharpe", 0))
    metrics["calmar"] = metrics.get("return_drawdown_ratio", metrics.get("calmar", 0))
    return _json_safe(metrics)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _real_backtest(
    strategy_code: str,
    class_name: str,
    vt_symbol: str,
    parameters: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    from vnpy_ctastrategy.backtesting import BacktestingEngine

    interval = _interval_value(str(config.get("interval") or "1m"))
    coverage = coverage_service.get_data_coverage(
        *local_data_provider.split_vt_symbol(vt_symbol),
        interval,
        start_date=config.get("start_date"),
        end_date=config.get("end_date"),
    )
    requested_start_text = config.get("start_date")
    requested_end_text = config.get("end_date")
    start_text = requested_start_text or coverage.get("local_start")
    end_text = requested_end_text or coverage.get("local_end")
    if coverage["status"] not in {"covered", "available"} or not start_text or not end_text:
        diagnostics = [
            {
                "level": "error",
                "message": "market data coverage is missing or partial",
                "missing_ranges": coverage.get("missing_ranges", []),
                "suggestion": "Call POST /api/data/download before running a real backtest.",
            }
        ]
        return _failure("market data coverage is missing or partial", diagnostics)

    start = _parse_datetime(start_text)
    end = _parse_datetime(end_text, fallback=start.isoformat())
    local_start = _parse_datetime(coverage.get("local_start")) if coverage.get("local_start") else None
    local_end = _parse_datetime(coverage.get("local_end")) if coverage.get("local_end") else None
    if _is_date_only(requested_start_text) and local_start and local_start.date() == start.date():
        start = local_start
    if _is_date_only(requested_end_text):
        if local_end and local_end.date() == end.date():
            end = local_end
        else:
            end = datetime.combine(end.date(), time(23, 59, 59))
    bars = local_data_provider.load_bar_data(vt_symbol, interval, start, end)
    if not bars:
        return _failure(
            "market data coverage is missing or partial",
            [
                {
                    "level": "error",
                    "message": "no local bars found for requested backtest range",
                    "missing_ranges": coverage.get("missing_ranges", []),
                    "suggestion": "Call POST /api/data/download before running a real backtest.",
                }
            ],
        )

    strategy_class = _load_strategy_class(strategy_code, class_name)
    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=vt_symbol,
        interval=_vnpy_interval(interval),
        start=start,
        end=end,
        rate=float(config.get("rate", 0.000045)),
        slippage=float(config.get("slippage", 0.001)),
        size=float(config.get("size", 1)),
        pricetick=float(config.get("pricetick", 0.001)),
        capital=int(float(config.get("capital", 100000))),
        annual_days=int(config.get("annual_days", 240)),
    )
    engine.add_strategy(strategy_class, dict(parameters or {}))
    engine.history_data = bars
    engine.run_backtesting()
    daily_df = engine.calculate_result()
    statistics = engine.calculate_statistics(daily_df, output=False)
    daily_results = _records_from_daily_df(daily_df)
    trades = _trade_records(engine.get_all_trades())
    return {
        "success": True,
        "metrics": _metric_aliases(statistics),
        "daily_results": _json_safe(daily_results),
        "trades": trades,
        "logs": list(getattr(engine, "logs", []) or []),
        "diagnostics": [
            _diagnostic("info", f"real vn.py CTA backtest completed with {len(bars)} local bars"),
            _diagnostic("info", "market data loaded from local SQLite bars table"),
        ],
        "engine_name": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "error": None,
    }


def run_backtest(
    strategy_code: str,
    class_name: str,
    vt_symbol: str,
    parameters: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    resolved_config = dict(config or {})
    mode = str(resolved_config.get("mode") or "real").strip().lower()
    if mode == "mock":
        return _mock_result(resolved_config)
    if mode != "real":
        return _failure(f"unsupported backtesting mode: {mode}")
    try:
        return _real_backtest(strategy_code, class_name, vt_symbol, parameters, resolved_config)
    except Exception as exc:
        return _failure(str(exc), [_diagnostic("error", str(exc))])
