"""执行监控：只读交易引擎（executor）写在 storage/executor 下的数据库，供平台页面展示。

运行记录：live（实盘）、paper（纸面）、backtest:<名称>（回测）。平台不导入引擎代码，只按表结构读取。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.paths import STORAGE_ROOT

EXECUTOR_ROOT = STORAGE_ROOT / "executor"
ALERT_KINDS = ("order_rejected", "order_blocked", "intent_blocked", "intent_expired", "gateway_down",
               "unknown_or_duplicate_trade", "start")


def _runs() -> list[dict[str, Any]]:
    out = []
    for kind, label in (("live", "实盘"), ("paper", "纸面")):
        p = EXECUTOR_ROOT / f"{kind}.sqlite"
        if p.is_file():
            out.append({"id": kind, "kind": kind, "label": label, "path": p})
    for p in sorted((EXECUTOR_ROOT / "backtests").glob("*/executor.sqlite")):
        out.append({"id": f"backtest:{p.parent.name}", "kind": "backtest", "label": f"回测 {p.parent.name}", "path": p})
    return out


def list_runs() -> dict:
    items = [{"id": r["id"], "kind": r["kind"], "label": r["label"],
              "updated": datetime.fromtimestamp(r["path"].stat().st_mtime).isoformat(timespec="seconds")} for r in _runs()]
    return {"items": sorted(items, key=lambda x: (x["kind"] != "live", x["kind"] != "paper", x["updated"]), reverse=False)}


def _path(run_id: str) -> Path:
    if not re.fullmatch(r"(live|paper|backtest:[\w\-\.]+)", run_id or ""):
        raise ValueError("无效的运行记录")
    for r in _runs():
        if r["id"] == run_id:
            return r["path"]
    raise FileNotFoundError(f"找不到运行记录：{run_id}")


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def overview(run_id: str) -> dict:
    path = _path(run_id)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        books = {r["strategy"]: json.loads(r["payload"]) for r in _rows(conn, "SELECT strategy, payload FROM books")}
        equity = _rows(conn, "SELECT day, strategy, equity FROM equity ORDER BY day")
        last_day = max((r["day"] for r in equity), default=None)
        strategies = []
        for name, book in sorted(books.items()):
            series = [{"day": r["day"], "equity": round(r["equity"], 2)} for r in equity if r["strategy"] == name]
            dec = _rows(conn, "SELECT time, payload FROM decisions WHERE strategy = ? ORDER BY id DESC LIMIT 1", (name,))
            latest = json.loads(dec[0]["payload"]) | {"time": dec[0]["time"]} if dec else {}
            today = last_day or ""
            counts = _rows(conn, "SELECT kind, count(*) AS n FROM events WHERE strategy = ? AND substr(time,1,10) = ? GROUP BY kind",
                           (name, today))
            strategies.append({
                "name": name, "capital": book["capital"], "cash": round(book["cash"], 2), "positions": book["positions"],
                "fees": round(book.get("fees", 0.0), 2), "dividends": round(book.get("dividends", 0.0), 2),
                "equity": series[-1]["equity"] if series else book["capital"],
                "return_pct": round((series[-1]["equity"] / book["capital"] - 1) * 100, 2) if series else 0.0,
                "series": series, "latest_decision": latest,
                "today": {r["kind"]: r["n"] for r in counts},
            })
        alerts = _rows(conn, f"SELECT time, kind, strategy, payload FROM events WHERE kind IN ({','.join('?' * len(ALERT_KINDS))}) "
                             "ORDER BY id DESC LIMIT 100", ALERT_KINDS)
        trades = _rows(conn, "SELECT time, strategy, symbol, side, price, volume, fee FROM trades ORDER BY time DESC LIMIT 200")
        orders = _rows(conn, "SELECT created, updated, strategy, symbol, side, price, volume, filled, avg_price, status, reason "
                             "FROM orders ORDER BY created DESC LIMIT 200")
    finally:
        conn.close()
    report = {}
    report_path = path.parent / "report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    for a in alerts:
        a["payload"] = json.loads(a["payload"] or "{}")
    return {"run": run_id, "last_day": last_day, "strategies": strategies, "alerts": alerts, "trades": trades,
            "orders": orders, "report": report}
