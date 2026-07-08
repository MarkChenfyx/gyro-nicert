from __future__ import annotations

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
    source_type TEXT NOT NULL,
    source_text TEXT,
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


def initialize_database(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(schema)
        connection.commit()


def main() -> None:
    ensure_directories()
    initialize_database(DB_ROOT / "app.sqlite", APP_SCHEMA)
    initialize_database(DB_ROOT / "market_data.sqlite", MARKET_SCHEMA)
    print(f"Initialized app database: {DB_ROOT / 'app.sqlite'}")
    print(f"Initialized market database: {DB_ROOT / 'market_data.sqlite'}")


if __name__ == "__main__":
    main()
