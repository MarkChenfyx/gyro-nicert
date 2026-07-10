from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.paths import DB_ROOT, ensure_directories


APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    message TEXT,
    error TEXT,
    related_strategy_id TEXT,
    related_run_id TEXT,
    related_pool_item_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_family TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_text TEXT,
    class_name TEXT,
    code_path TEXT NOT NULL,
    code_hash TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    task_id TEXT,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_variants (
    variant_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    variant_name TEXT NOT NULL,
    params_hash TEXT,
    config_path TEXT,
    result_path TEXT NOT NULL,
    daily_results_path TEXT,
    trades_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pool_items (
    pool_item_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    source_variant_id TEXT NOT NULL,
    pool_path TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_family TEXT,
    strategy_version TEXT,
    vt_symbol TEXT,
    annual_return REAL,
    max_drawdown REAL,
    sharpe REAL,
    calmar REAL,
    tags TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT NOT NULL
);
"""


MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS download_tasks (
    download_task_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bars_1m (
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    datetime TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    turnover REAL,
    open_interest REAL,
    PRIMARY KEY (symbol, exchange, datetime)
);

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


APP_RESET = """
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS strategies;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS run_variants;
DROP TABLE IF EXISTS pool_items;
DROP TABLE IF EXISTS artifacts;
"""


MARKET_RESET = """
DROP TABLE IF EXISTS data_coverage;
DROP TABLE IF EXISTS download_tasks;
DROP TABLE IF EXISTS bars_1m;
DROP TABLE IF EXISTS bars;
"""


def initialize_database(path: Path, schema: str, *, reset: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(schema if reset else schema.replace(APP_RESET, "").replace(MARKET_RESET, ""))
        connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop and recreate app tables only")
    parser.add_argument("--reset-app", action="store_true", help="drop and recreate app tables only")
    parser.add_argument("--reset-market", action="store_true", help="drop and recreate market tables")
    parser.add_argument("--reset-all", action="store_true", help="drop and recreate both app and market tables")
    args = parser.parse_args()
    ensure_directories()

    reset_app = bool(args.reset or args.reset_app or args.reset_all)
    reset_market = bool(args.reset_market or args.reset_all)

    initialize_database(DB_ROOT / "app.sqlite", f"{APP_RESET}{APP_SCHEMA}", reset=reset_app)
    initialize_database(DB_ROOT / "market_data.sqlite", f"{MARKET_RESET}{MARKET_SCHEMA}", reset=reset_market)
    print(f"Initialized app database: {DB_ROOT / 'app.sqlite'}")
    print(f"Initialized market database: {DB_ROOT / 'market_data.sqlite'}")


if __name__ == "__main__":
    main()
