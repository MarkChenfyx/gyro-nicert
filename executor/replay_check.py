"""每日重放核对：用当天录下的行情、从前一交易日收盘的账本和策略状态出发重跑一遍，与实盘（或纸面）记录逐项比较。

  python -m executor.replay_check --config executor/config.toml --db storage/executor/live.sqlite --date 2026-10-16

三层比较：
  数据：当天每个标的录到的快照数量（重放用的就是这些数据，数据层天然一致；数量异常说明录制缺失）。
  决策：同一决策时点、同一策略的动作（建仓/换到某只/不动/跳过）是否一致。应完全一致，否则说明策略不确定或状态没恢复对。
  执行：实盘成交价相对决策时中间价的成本、从报单到成交的时间，与模拟撮合对比。
报告写到 <runtime_dir>/replay_checks/<日期>.json。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .clock import SimClock
from .data import iter_quotes, load_actions, read_symbol
from .engine import Engine
from .gateways.sim import ReplayMarket, SimBroker
from .portfolio import Book
from .risk import RiskConfig, RiskManager
from .runner import build_strategies, resolve
from .store import Store


def _prev_day(conn: sqlite3.Connection, day: date) -> str | None:
    row = conn.execute("SELECT max(day) FROM state_history WHERE day < ?", (day.isoformat(),)).fetchone()
    return row[0] if row and row[0] else None


def replay_day(cfg: dict, live_db: Path, data_dir: Path, day: date) -> dict:
    live = Store(live_db)
    prev = _prev_day(live.conn, day)
    if prev is None:
        return {"日期": str(day), "错误": "实盘库里没有前一交易日的收盘状态"}
    start_state = live.history(date.fromisoformat(prev))
    strategies = build_strategies(cfg)
    capitals = {s["name"]: float(s["capital"]) for s in cfg["strategy"]}
    tmp_dir = Path(tempfile.mkdtemp())
    store = Store(tmp_dir / "replay.sqlite")
    positions, cash = {}, 0.0
    for name, (book, state) in start_state.items():
        store.save_book(datetime.fromisoformat(prev), book)
        store.save_state(datetime.fromisoformat(prev), name, state)
        b = Book.from_dict(book)
        cash += b.cash
        for s, q in b.positions.items():
            positions[s] = positions.get(s, 0) + q
    store.commit()
    eng_cfg, sim = cfg["engine"], cfg.get("sim", {})
    clock = SimClock()
    broker = SimBroker(clock, cash, sim.get("latency_seconds", 0.0), eng_cfg.get("commission_bp", 1.0),
                       tplus1=set(eng_cfg.get("tplus1", [])), actions=load_actions(data_dir))
    broker.positions = positions
    engine = Engine(clock=clock, market_gw=ReplayMarket(), trade_gw=broker, strategies=strategies, capitals=capitals,
                    store=store, risk=RiskManager(RiskConfig(**{**cfg.get("risk", {}), "stop_file": ""})),
                    tplus1=set(eng_cfg.get("tplus1", [])), commission_bp=eng_cfg.get("commission_bp", 1.0),
                    max_quote_age=eng_cfg.get("max_quote_age_seconds", 90.0), actions=load_actions(data_dir))
    engine.start()
    start, end = datetime.combine(day, datetime.min.time()), datetime.combine(day + timedelta(days=1), datetime.min.time())
    symbols = sorted({s for st in strategies for s in st.symbols})
    for t, quotes in iter_quotes(data_dir, symbols, start, end):
        engine.on_quotes(t, quotes)
    engine.finish()

    data_layer = {s: len(read_symbol(data_dir, s, start, end)) for s in symbols}
    live_dec = {(t[:16], s): p for t, s, p in live.decisions_on(day)}
    rep_dec = {(t[:16], s): p for t, s, p in store.decisions_on(day)}
    mismatches = []
    for key in sorted(set(live_dec) | set(rep_dec)):
        a, b = live_dec.get(key, {}).get("action"), rep_dec.get(key, {}).get("action")
        if a != b:
            mismatches.append({"时点": key[0], "策略": key[1], "实盘": a, "重放": b})
    trades = pd.read_sql("SELECT strategy, symbol, side, price, volume, time FROM trades WHERE substr(time,1,10)=?",
                         live.conn, params=(day.isoformat(),))
    orders = pd.read_sql("SELECT client_id, created, updated, status FROM orders WHERE substr(created,1,10)=?",
                         live.conn, params=(day.isoformat(),))
    rep_trades = pd.read_sql("SELECT strategy, symbol, side, price, volume, time FROM trades", store.conn)
    execution = {
        "实盘成交笔数": len(trades), "重放成交笔数": len(rep_trades),
        "实盘成交额": round(float((trades.price * trades.volume).sum()), 2),
        "重放成交额": round(float((rep_trades.price * rep_trades.volume).sum()), 2),
        "实盘委托数": len(orders),
        "实盘未完全成交委托": int((orders.status != "FILLED").sum()) if len(orders) else 0,
    }
    store.conn.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"日期": str(day), "起点状态日": prev, "数据层_各标的快照数": data_layer,
            "决策层_时点数": len(live_dec), "决策层_不一致": len(mismatches), "不一致样例": mismatches[:20],
            "执行层": execution}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="executor/config.toml")
    ap.add_argument("--db", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--data-dir")
    args = ap.parse_args()
    cfg = tomllib.loads(resolve(args.config).read_text(encoding="utf-8"))
    data_dir = Path(args.data_dir) if args.data_dir else resolve(cfg["engine"].get("data_dir", "storage/executor/ticks"))
    report = replay_day(cfg, resolve(args.db), data_dir, date.fromisoformat(args.date))
    out = resolve(cfg["engine"].get("runtime_dir", "storage/executor")) / "replay_checks" / f"{args.date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
