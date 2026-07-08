from __future__ import annotations

from datetime import datetime
from typing import Any

from data_manager.database import get_market_db_connection


def _parse_datetime(value: str) -> datetime:
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text[:10] + "T00:00:00")


def _vnpy_exchange(exchange: str):
    from vnpy.trader.constant import Exchange

    try:
        return Exchange(str(exchange).upper())
    except ValueError:
        return getattr(Exchange, str(exchange).upper())


def _vnpy_interval(interval: str):
    from vnpy.trader.constant import Interval

    normalized = str(interval or "1m").lower()
    if normalized in {"1m", "1min", "minute"}:
        return Interval.MINUTE
    if normalized in {"1d", "d", "day", "daily"}:
        return Interval.DAILY
    if normalized in {"1h", "60m", "hour"}:
        return Interval.HOUR
    raise ValueError(f"Unsupported vn.py backtest interval: {interval}")


def split_vt_symbol(vt_symbol: str) -> tuple[str, str]:
    parts = str(vt_symbol or "").split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid vt_symbol, expected SYMBOL.EXCHANGE: {vt_symbol}")
    return parts[0], parts[1].upper()


def load_bar_rows(
    symbol: str,
    exchange: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    with get_market_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT symbol, exchange, interval, datetime, open, high, low, close,
                   volume, turnover, open_interest
            FROM bars
            WHERE symbol = ?
              AND exchange = ?
              AND interval = ?
              AND datetime >= ?
              AND datetime <= ?
            ORDER BY datetime ASC
            """,
            (symbol, exchange, interval, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def rows_to_bar_data(rows: list[dict[str, Any]]) -> list[Any]:
    from vnpy.trader.object import BarData

    bars = []
    for row in rows:
        bars.append(
            BarData(
                gateway_name="LOCAL",
                symbol=str(row["symbol"]),
                exchange=_vnpy_exchange(str(row["exchange"])),
                datetime=_parse_datetime(str(row["datetime"])),
                interval=_vnpy_interval(str(row["interval"])),
                volume=float(row.get("volume") or 0),
                turnover=float(row.get("turnover") or 0),
                open_interest=float(row.get("open_interest") or 0),
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
            )
        )
    return bars


def load_bar_data(
    vt_symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[Any]:
    symbol, exchange = split_vt_symbol(vt_symbol)
    return rows_to_bar_data(load_bar_rows(symbol, exchange, interval, start, end))
