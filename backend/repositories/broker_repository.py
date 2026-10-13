from __future__ import annotations

import json
from typing import Any

from backend.data_manager.database import get_app_db_connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_captures (
    capture_id TEXT PRIMARY KEY, source_hash TEXT NOT NULL UNIQUE,
    trade_date TEXT NOT NULL, captured_at TEXT NOT NULL,
    artifact_path TEXT NOT NULL, counts_json TEXT NOT NULL, warnings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_account_daily (
    account_key TEXT NOT NULL, account_label TEXT NOT NULL, trade_date TEXT NOT NULL,
    capture_id TEXT NOT NULL, captured_at TEXT NOT NULL,
    total_assets REAL, available_cash REAL, withdrawable_cash REAL,
    total_market_value REAL, stock_market_value REAL, fund_market_value REAL,
    profit_loss REAL, login_status TEXT,
    PRIMARY KEY (account_key, trade_date)
);
CREATE TABLE IF NOT EXISTS broker_positions (
    account_key TEXT NOT NULL, trade_date TEXT NOT NULL, capture_id TEXT NOT NULL,
    market TEXT NOT NULL, symbol TEXT NOT NULL, vt_symbol TEXT NOT NULL,
    quantity REAL, available_quantity REAL, in_transit REAL, frozen_quantity REAL,
    overnight_quantity REAL, cost_price REAL, market_value REAL, profit_loss REAL,
    PRIMARY KEY (account_key, trade_date, vt_symbol)
);
CREATE TABLE IF NOT EXISTS broker_orders (
    order_key TEXT PRIMARY KEY, account_key TEXT NOT NULL, trade_date TEXT NOT NULL,
    capture_id TEXT NOT NULL, order_time TEXT, market TEXT, symbol TEXT, vt_symbol TEXT,
    action TEXT, quote_type TEXT, order_price REAL, order_quantity REAL,
    filled_quantity REAL, filled_average_price REAL, filled_amount REAL,
    canceled_quantity REAL, status TEXT, entrust_id TEXT, order_id TEXT,
    strategy_name TEXT, remark TEXT, reject_reason TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_deals (
    deal_key TEXT PRIMARY KEY, account_key TEXT NOT NULL, trade_date TEXT NOT NULL,
    capture_id TEXT NOT NULL, deal_time TEXT, market TEXT, symbol TEXT, vt_symbol TEXT,
    action TEXT, price REAL, quantity REAL, amount REAL, fee REAL,
    entrust_id TEXT, trade_id TEXT, order_id TEXT, strategy_name TEXT, remark TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_settlements (
    settlement_key TEXT PRIMARY KEY, account_key TEXT NOT NULL, trade_date TEXT NOT NULL,
    capture_id TEXT NOT NULL, deal_time TEXT, symbol TEXT, vt_symbol TEXT, security_name TEXT,
    action TEXT, price REAL, quantity REAL, amount REAL, fee REAL, stamp_tax REAL, other_fee REAL,
    cash_balance REAL, share_balance REAL, entrust_id TEXT, trade_id TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_fund_flows (
    flow_key TEXT PRIMARY KEY, account_key TEXT NOT NULL, trade_date TEXT NOT NULL,
    capture_id TEXT NOT NULL, flow_time TEXT, serial TEXT, business TEXT, category TEXT,
    amount REAL, balance REAL, symbol TEXT, vt_symbol TEXT, security_name TEXT,
    quantity REAL, price REAL, fee REAL, updated_at TEXT NOT NULL
);
"""


def _connect():
    connection = get_app_db_connection()
    connection.executescript(SCHEMA)
    return connection


def find_capture(source_hash: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM broker_captures WHERE source_hash = ?", (source_hash,)).fetchone()
    return dict(row) if row else None


def save_capture(capture: dict[str, Any], accounts: list[dict[str, Any]], positions: list[dict[str, Any]], orders: list[dict[str, Any]], deals: list[dict[str, Any]], settlements: list[dict[str, Any]] | None = None, flows: list[dict[str, Any]] | None = None) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO broker_captures VALUES (?, ?, ?, ?, ?, ?, ?)",
            (capture["capture_id"], capture["source_hash"], capture["trade_date"], capture["captured_at"],
             capture["artifact_path"], json.dumps(capture["counts"], ensure_ascii=False), json.dumps(capture["warnings"], ensure_ascii=False)),
        )
        for row in accounts:
            connection.execute(
                """INSERT INTO broker_account_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_key, trade_date) DO UPDATE SET
                account_label=excluded.account_label, capture_id=excluded.capture_id, captured_at=excluded.captured_at,
                total_assets=excluded.total_assets, available_cash=excluded.available_cash,
                withdrawable_cash=excluded.withdrawable_cash, total_market_value=excluded.total_market_value,
                stock_market_value=excluded.stock_market_value, fund_market_value=excluded.fund_market_value,
                profit_loss=excluded.profit_loss, login_status=excluded.login_status""",
                tuple(row[key] for key in ("account_key", "account_label", "trade_date", "capture_id", "captured_at", "total_assets", "available_cash", "withdrawable_cash", "total_market_value", "stock_market_value", "fund_market_value", "profit_loss", "login_status")),
            )
        account_dates = {(row["account_key"], row["trade_date"]) for row in accounts}
        account_dates.update((row["account_key"], row["trade_date"]) for row in positions)
        for account_key, trade_date in account_dates:
            connection.execute("DELETE FROM broker_positions WHERE account_key=? AND trade_date=?", (account_key, trade_date))
        connection.executemany(
            "INSERT INTO broker_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row[key] for key in ("account_key", "trade_date", "capture_id", "market", "symbol", "vt_symbol", "quantity", "available_quantity", "in_transit", "frozen_quantity", "overnight_quantity", "cost_price", "market_value", "profit_loss")) for row in positions],
        )
        for table, rows in (("broker_orders", orders), ("broker_deals", deals),
                            ("broker_settlements", settlements or []), ("broker_fund_flows", flows or [])):
            if not rows:
                continue
            columns = list(rows[0])
            placeholders = ",".join("?" for _ in columns)
            updates = ",".join(f"{column}=excluded.{column}" for column in columns if not column.endswith("_key"))
            connection.executemany(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT({columns[0]}) DO UPDATE SET {updates}",
                [tuple(row[column] for column in columns) for row in rows],
            )
        connection.commit()


def latest_capture() -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM broker_captures ORDER BY captured_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    result = dict(row)
    result["counts"] = json.loads(result.pop("counts_json"))
    result["warnings"] = json.loads(result.pop("warnings_json"))
    return result


def overview_rows(limit: int = 200) -> dict[str, Any]:
    with _connect() as connection:
        account = connection.execute("SELECT * FROM broker_account_daily ORDER BY trade_date DESC, captured_at DESC LIMIT 1").fetchone()
        account_key = str(account["account_key"]) if account else ""
        trade_date = str(account["trade_date"]) if account else ""
        curve = connection.execute("SELECT * FROM broker_account_daily WHERE account_key=? ORDER BY trade_date", (account_key,)).fetchall() if account else []
        positions = connection.execute("SELECT * FROM broker_positions WHERE account_key=? AND trade_date=? ORDER BY market_value DESC", (account_key, trade_date)).fetchall() if account else []
        order_date_row = connection.execute("SELECT MAX(trade_date) AS value FROM broker_orders WHERE account_key=?", (account_key,)).fetchone() if account else None
        deal_date_row = connection.execute("SELECT MAX(trade_date) AS value FROM broker_deals WHERE account_key=?", (account_key,)).fetchone() if account else None
        order_date = str(order_date_row["value"] or "") if order_date_row else ""
        deal_date = str(deal_date_row["value"] or "") if deal_date_row else ""
        orders = connection.execute("SELECT * FROM broker_orders WHERE account_key=? AND trade_date=? ORDER BY order_time DESC LIMIT ?", (account_key, order_date, limit)).fetchall() if order_date else []
        deals = connection.execute("SELECT * FROM broker_deals WHERE account_key=? AND trade_date=? ORDER BY deal_time DESC LIMIT ?", (account_key, deal_date, limit)).fetchall() if deal_date else []
        # 交割单和资金流水是 T+1 的已清算记录，按时间倒序取最近若干条，并按标的汇总真实费率。
        settlements = connection.execute("SELECT * FROM broker_settlements WHERE account_key=? ORDER BY trade_date DESC, deal_time DESC LIMIT ?", (account_key, limit)).fetchall() if account else []
        fees = connection.execute(
            """SELECT vt_symbol, COUNT(*) AS trades, SUM(ABS(COALESCE(amount, 0))) AS amount,
            SUM(COALESCE(fee, 0) + COALESCE(stamp_tax, 0) + COALESCE(other_fee, 0)) AS fee,
            MIN(trade_date) AS first_date, MAX(trade_date) AS last_date
            FROM broker_settlements WHERE account_key=? GROUP BY vt_symbol ORDER BY amount DESC""",
            (account_key,)).fetchall() if account else []
        flows = connection.execute("SELECT * FROM broker_fund_flows WHERE account_key=? ORDER BY trade_date DESC, flow_time DESC LIMIT ?", (account_key, limit)).fetchall() if account else []
        cash = connection.execute(
            """SELECT category, COUNT(*) AS count, SUM(COALESCE(amount, 0)) AS amount
            FROM broker_fund_flows WHERE account_key=? GROUP BY category ORDER BY ABS(SUM(COALESCE(amount, 0))) DESC""",
            (account_key,)).fetchall() if account else []
    return {
        "account": dict(account) if account else None,
        "asset_curve": [dict(row) for row in curve],
        "positions": [dict(row) for row in positions],
        "orders": [dict(row) for row in orders],
        "deals": [dict(row) for row in deals],
        "settlements": [dict(row) for row in settlements],
        "fee_summary": [dict(row) for row in fees],
        "fund_flows": [dict(row) for row in flows],
        "cash_summary": [dict(row) for row in cash],
        "dates": {"account": trade_date, "positions": trade_date, "orders": order_date, "deals": deal_date},
    }
