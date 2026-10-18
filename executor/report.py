"""回测报告：每个策略的日收益、对组内等权一直持有的超额、换仓次数、成交价相对中间价的成本。

基准 = 组内各 ETF 每日收盘（最后快照中间价）收益的等权平均，现金分红加回、拆分按比例还原。
统计从策略首次持仓的下一个交易日开始（预热期不计）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .data import iter_events, load_actions, read_symbol


def daily_mid(data_dir: Path, symbol: str, start: datetime, end: datetime) -> pd.Series:
    f = read_symbol(data_dir, symbol, start, end)
    if f.empty and list(Path(data_dir).glob("events_*.jsonl")):
        prices = {q.time:q.mid for kind,_,quotes in iter_events(data_dir,[symbol],start,end)
                  for q in quotes if kind=="quotes" and q.valid}
        if not prices:
            return pd.Series(dtype=float)
        s=pd.Series(prices).sort_index()
        return s.groupby(s.index.normalize()).last()
    f = f[(f.bid1 > 0) & (f.ask1 > 0)]
    mid = (f.bid1 + f.ask1) / 2
    return mid.groupby(mid.index.normalize()).last()


def benchmark(data_dir: Path, symbols: list[str], start: datetime, end: datetime) -> pd.Series:
    acts = pd.DataFrame([a.__dict__ for a in load_actions(data_dir)])
    rets = {}
    for s in symbols:
        m = daily_mid(data_dir, s, start, end)
        adj = m.copy()
        if not acts.empty:
            for a in acts[acts.symbol == s].itertuples():
                d = pd.Timestamp(a.date).normalize()
                if d in adj.index:
                    adj.loc[d] = adj.loc[d] * a.split_ratio + a.cash_per_share
        rets[s] = adj / m.shift(1) - 1
    return pd.DataFrame(rets).mean(axis=1)


def summarize(db_path: Path, data_dir: Path, strategies: list[dict], start: datetime, end: datetime) -> dict:
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    eq = pd.read_sql("SELECT day, strategy, equity, positions FROM equity", conn, parse_dates=["day"])
    trades = pd.read_sql("SELECT strategy, side, price, volume, time, fee FROM trades", conn, parse_dates=["time"])
    unit = pd.read_sql("SELECT day, strategy, daily_return FROM unit_returns", conn, parse_dates=["day"])
    intents = pd.read_sql("SELECT strategy, kind FROM events WHERE kind LIKE 'intent%'", conn)
    conn.close()
    out, curves = {}, {}
    for cfg in strategies:
        name = cfg["name"]
        e = eq[eq.strategy == name].set_index("day").sort_index()
        held = e.positions.map(lambda p: bool(json.loads(p)))
        if not held.any():
            out[name] = {"说明": "从未建仓"}
            continue
        first = held[held].index[0]
        r = unit[unit.strategy == name].set_index("day").daily_return / 100.0
        b = benchmark(data_dir, cfg["symbols"], start, end).reindex(r.index)
        x = pd.DataFrame({"策略": r, "基准": b}).loc[first:].iloc[1:].dropna()
        if x.empty:
            out[name] = {"说明": "尚无可计算的单位仓位收益"}
            continue
        ex = x.策略 - x.基准
        years = len(x) / 252
        k = intents[intents.strategy == name].kind.value_counts()
        tr = trades[trades.strategy == name]
        out[name] = {
            "统计起点": str(first.date()), "交易日": len(x),
            "年化收益%": round(x.策略.sum() / years * 100, 2), "基准年化%": round(x.基准.sum() / years * 100, 2),
            "年化超额%": round(ex.sum() / years * 100, 2),
            "超额夏普": round(ex.mean() / ex.std() * np.sqrt(252), 2) if ex.std() > 0 else 0.0,
            "超额最大回撤%": round(((ex.cumsum() - ex.cumsum().cummax().clip(lower=0)).min()) * 100, 2),
            "每年换仓": round(k.get("intent_done", 0) / years, 1), "过期意图": int(k.get("intent_expired", 0)),
            "被拦截意图": int(k.get("intent_blocked", 0)), "成交笔数": len(tr), "手续费": round(tr.fee.sum(), 2),
        }
        curves[name] = ex.cumsum() * 100
    return {"return_basis": "unit_position", "summary": out, "excess_curves": {k: {str(d.date()): round(v, 4) for d, v in s.items()} for k, s in curves.items()}}
