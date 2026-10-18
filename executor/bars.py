"""统一的报价采样时间 K 线。只分发已结束窗口，明确标记缺分钟的窗口。

OHLC 来自实际收到的 Quote.last 样本，不宣称等同交易所逐笔成交生成的 K 线。
历史一分钟采样通过 interval_end=True 标明结束时间；tick 使用左闭右开窗口。
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timedelta
from .events import Quote, Bar

class BarGenerator:
    def __init__(self):
        self.periods = {}
        self.pending = {}

    def subscribe(self, symbol, periods):
        for m in periods:
            if not isinstance(m, int) or m <= 0 or m > 120:
                raise ValueError("K线周期应为1至120分钟的整数")
        self.periods.setdefault(symbol, set()).update(periods)

    def update(self, q: Quote, closed_through=None):
        if not q.valid or q.last <= 0:
            return
        t = q.time - timedelta(microseconds=1) if q.interval_end else q.time
        anchor = t.replace(hour=9 if t.hour < 12 else 13, minute=30 if t.hour < 12 else 0, second=0, microsecond=0)
        limit = anchor.replace(hour=11 if t.hour < 12 else 15, minute=30 if t.hour < 12 else 0)
        if t < anchor or t >= limit:
            return
        for minutes in self.periods.get(q.symbol, ()):
            start = anchor + timedelta(minutes=int((t-anchor).total_seconds()//60)//minutes*minutes)
            end = min(start+timedelta(minutes=minutes), limit)
            if closed_through and end <= closed_through:
                continue
            key = (q.symbol, minutes, start.isoformat())
            b = self.pending.setdefault(key, {"symbol":q.symbol,"start":start.isoformat(),"end":end.isoformat(),
                "minutes":minutes,"open":q.last,"high":q.last,"low":q.last,"close":q.last,"samples":0,"seen":[]})
            b["high"], b["low"], b["close"] = max(b["high"],q.last), min(b["low"],q.last), q.last
            b["samples"] += 1
            minute = t.replace(second=0,microsecond=0).isoformat()
            if minute not in b["seen"]:
                b["seen"].append(minute)

    def advance(self, cutoff):
        ready=[]
        for key,b in list(self.pending.items()):
            if datetime.fromisoformat(b["end"]) <= cutoff:
                x=dict(b); seen=x.pop("seen")
                x["start"],x["end"] = datetime.fromisoformat(x["start"]),datetime.fromisoformat(x["end"])
                x["complete"] = len(seen) == int((x["end"]-x["start"]).total_seconds()/60)
                ready.append(Bar(**x)); del self.pending[key]
        return sorted(ready,key=lambda b:(b.end,b.minutes,b.symbol))

    def state(self):
        return list(self.pending.values())

    def restore(self, state):
        self.pending = {(b["symbol"],b["minutes"],b["start"]):b for b in state}
