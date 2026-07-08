from __future__ import annotations

import sqlite3

from backend.core.paths import DB_ROOT


APP_DB_PATH = DB_ROOT / "app.sqlite"
MARKET_DB_PATH = DB_ROOT / "market_data.sqlite"


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def get_app_db_connection() -> sqlite3.Connection:
    return _connect(str(APP_DB_PATH))


def get_market_db_connection() -> sqlite3.Connection:
    return _connect(str(MARKET_DB_PATH))

