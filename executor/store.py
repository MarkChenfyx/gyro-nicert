"""持久化：SQLite 保存委托、成交、决策、账本、策略状态和每日权益；同时按天写 JSONL 流水，便于人工查看。

平台页面只读这个数据库。回测时传入单独的路径，不与实盘记录混在一起。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .events import Order, OrderStatus, Side, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, kind TEXT, strategy TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS orders (client_id TEXT PRIMARY KEY, strategy TEXT, intent_id TEXT, symbol TEXT, side TEXT,
    price REAL, volume INTEGER, status TEXT, filled INTEGER, avg_price REAL, broker_id TEXT, created TEXT, updated TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS trades (trade_id TEXT PRIMARY KEY, client_id TEXT, strategy TEXT, symbol TEXT, side TEXT,
    price REAL, volume INTEGER, time TEXT, fee REAL);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, strategy TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS books (strategy TEXT PRIMARY KEY, payload TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS strategy_state (strategy TEXT PRIMARY KEY, payload TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS state_history (day TEXT, strategy TEXT, book TEXT, state TEXT, PRIMARY KEY (day, strategy));
CREATE TABLE IF NOT EXISTS equity (day TEXT, strategy TEXT, equity REAL, cash REAL, positions TEXT, PRIMARY KEY (day, strategy));
"""


def _ts(t: datetime | date | None) -> str | None:
    return t.isoformat() if t is not None else None


class Store:
    def __init__(self, db_path: Path, log_dir: Path | None = None):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(SCHEMA)
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def event(self, t: datetime, kind: str, strategy: str = "", **payload: Any) -> None:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        self.conn.execute("INSERT INTO events (time, kind, strategy, payload) VALUES (?,?,?,?)", (_ts(t), kind, strategy, text))
        if self.log_dir:
            with (self.log_dir / f"{t:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": _ts(t), "kind": kind, "strategy": strategy, **payload}, ensure_ascii=False, default=str) + "\n")

    def order(self, o: Order) -> None:
        self.conn.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (o.client_id, o.strategy, o.intent_id, o.symbol, o.side.value, o.price, o.volume, o.status.value,
                           o.filled, o.avg_price, o.broker_id, _ts(o.created), _ts(o.updated), o.reason))

    def trade(self, strategy: str, t: Trade) -> None:
        self.conn.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                          (t.trade_id, t.client_id, strategy, t.symbol, t.side.value, t.price, t.volume, _ts(t.time), t.fee))

    def decision(self, t: datetime, strategy: str, payload: dict) -> None:
        self.conn.execute("INSERT INTO decisions (time, strategy, payload) VALUES (?,?,?)",
                          (_ts(t), strategy, json.dumps(payload, ensure_ascii=False, default=str)))

    def save_book(self, t: datetime, book: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO books VALUES (?,?,?)", (book["strategy"], json.dumps(book), _ts(t)))

    def save_state(self, t: datetime, strategy: str, state: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO strategy_state VALUES (?,?,?)", (strategy, json.dumps(state), _ts(t)))

    def end_of_day(self, d: date, strategy: str, book: dict, state: dict, equity: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO state_history VALUES (?,?,?,?)", (_ts(d), strategy, json.dumps(book), json.dumps(state)))
        self.conn.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?,?)",
                          (_ts(d), strategy, equity, book["cash"], json.dumps(book["positions"])))
        self.commit()

    def commit(self) -> None:
        self.conn.commit()

    # ---- 恢复 ----
    def load_books(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT payload FROM books")]

    def load_states(self) -> dict[str, dict]:
        return {r[0]: json.loads(r[1]) for r in self.conn.execute("SELECT strategy, payload FROM strategy_state")}

    def load_orders(self) -> list[Order]:
        rows = self.conn.execute("SELECT client_id, strategy, intent_id, symbol, side, price, volume, status, filled, avg_price, "
                                 "broker_id, created, updated, reason FROM orders").fetchall()
        return [Order(r[0], r[1], r[2], r[3], Side(r[4]), r[5], r[6], datetime.fromisoformat(r[11]), OrderStatus(r[7]), r[8], r[9],
                      r[10], datetime.fromisoformat(r[12]) if r[12] else None, r[13] or "") for r in rows]

    def trade_ids(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT trade_id FROM trades")}

    def history(self, day: date) -> dict[str, tuple[dict, dict]]:
        rows = self.conn.execute("SELECT strategy, book, state FROM state_history WHERE day = ?", (_ts(day),)).fetchall()
        return {r[0]: (json.loads(r[1]), json.loads(r[2])) for r in rows}

    def decisions_on(self, day: date) -> list[tuple[str, str, dict]]:
        rows = self.conn.execute("SELECT time, strategy, payload FROM decisions WHERE substr(time,1,10) = ? ORDER BY id",
                                 (_ts(day),)).fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]
