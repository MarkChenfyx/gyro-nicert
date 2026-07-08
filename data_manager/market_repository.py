from __future__ import annotations

from typing import Any

from common.time_utils import now_iso
from data_manager.database import get_market_db_connection


MARKET_SCHEMA_EXTENSION = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    interval TEXT NOT NULL,
    datetime TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    turnover REAL,
    open_interest REAL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, exchange, interval, datetime)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_data_coverage_key
ON data_coverage(symbol, exchange, interval, source);
"""


def _now() -> str:
    return now_iso()


def ensure_market_schema() -> None:
    with get_market_db_connection() as connection:
        connection.executescript(MARKET_SCHEMA_EXTENSION)
        connection.commit()


def upsert_bars(
    symbol: str,
    exchange: str,
    interval: str,
    bars: list[dict[str, Any]],
    *,
    source: str = "rqdata",
) -> int:
    ensure_market_schema()
    if not bars:
        return 0
    updated_at = _now()
    rows = [
        (
            symbol,
            exchange,
            interval,
            str(bar["datetime"]),
            float(bar["open"]),
            float(bar["high"]),
            float(bar["low"]),
            float(bar["close"]),
            None if bar.get("volume") is None else float(bar.get("volume")),
            None if bar.get("turnover") is None else float(bar.get("turnover")),
            None if bar.get("open_interest") is None else float(bar.get("open_interest")),
            source,
            updated_at,
        )
        for bar in bars
    ]
    with get_market_db_connection() as connection:
        connection.executemany(
            """
            INSERT INTO bars (
                symbol, exchange, interval, datetime, open, high, low, close,
                volume, turnover, open_interest, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, exchange, interval, datetime)
            DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                turnover = excluded.turnover,
                open_interest = excluded.open_interest,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            rows,
        )
        connection.commit()
    refresh_coverage(symbol, exchange, interval, source=source)
    return len(rows)


def refresh_coverage(symbol: str, exchange: str, interval: str, *, source: str = "rqdata") -> dict[str, Any] | None:
    ensure_market_schema()
    with get_market_db_connection() as connection:
        row = connection.execute(
            """
            SELECT MIN(datetime) AS start_date, MAX(datetime) AS end_date, COUNT(*) AS bar_count
            FROM bars
            WHERE symbol = ? AND exchange = ? AND interval = ?
            """,
            (symbol, exchange, interval),
        ).fetchone()
        if row is None or not row["start_date"]:
            return None
        status = "available" if int(row["bar_count"] or 0) > 0 else "empty"
        updated_at = _now()
        connection.execute(
            """
            INSERT INTO data_coverage (symbol, exchange, interval, start_date, end_date, source, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, exchange, interval, source)
            DO UPDATE SET
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (symbol, exchange, interval, str(row["start_date"]), str(row["end_date"]), source, status, updated_at),
        )
        connection.commit()
    return get_coverage(symbol, exchange, interval, source=source)


def get_coverage(symbol: str, exchange: str, interval: str, *, source: str = "rqdata") -> dict[str, Any] | None:
    ensure_market_schema()
    with get_market_db_connection() as connection:
        row = connection.execute(
            """
            SELECT c.*, (
                SELECT COUNT(*)
                FROM bars b
                WHERE b.symbol = c.symbol AND b.exchange = c.exchange AND b.interval = c.interval
            ) AS bar_count
            FROM data_coverage c
            WHERE c.symbol = ? AND c.exchange = ? AND c.interval = ? AND c.source = ?
            """,
            (symbol, exchange, interval, source),
        ).fetchone()
    return dict(row) if row is not None else None


def list_symbols(limit: int = 1000) -> list[dict[str, Any]]:
    ensure_market_schema()
    safe_limit = max(1, min(int(limit or 1000), 5000))
    with get_market_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT symbol, exchange, interval, MIN(datetime) AS start_date, MAX(datetime) AS end_date, COUNT(*) AS bar_count
            FROM bars
            GROUP BY symbol, exchange, interval
            ORDER BY symbol, exchange, interval
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_download_task(
    download_task_id: str,
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
    *,
    status: str = "running",
    error: str = "",
) -> dict[str, Any]:
    ensure_market_schema()
    now = _now()
    with get_market_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO download_tasks (
                download_task_id, symbol, exchange, interval, start_date, end_date,
                status, retry_count, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (download_task_id, symbol, exchange, interval, start_date, end_date, status, error, now, now),
        )
        connection.commit()
    return get_download_task(download_task_id) or {}


def update_download_task(download_task_id: str, *, status: str, error: str = "") -> dict[str, Any]:
    ensure_market_schema()
    with get_market_db_connection() as connection:
        connection.execute(
            """
            UPDATE download_tasks
            SET status = ?, error = ?, updated_at = ?
            WHERE download_task_id = ?
            """,
            (status, error, _now(), download_task_id),
        )
        connection.commit()
    return get_download_task(download_task_id) or {}


def get_download_task(download_task_id: str) -> dict[str, Any] | None:
    ensure_market_schema()
    with get_market_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM download_tasks WHERE download_task_id = ?",
            (download_task_id,),
        ).fetchone()
    return dict(row) if row is not None else None
