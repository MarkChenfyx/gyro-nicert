"""行情文件读写与除权除息数据。录制、下载、回放共用同一种文件格式：

<data_dir>/<代码>/<任意名>.pkl   每个文件一张表：时间索引（每分钟最后一个快照），列 last, bid1, ask1, iopv
<data_dir>/corporate_actions.csv  列 date, symbol, cash_per_share, split_ratio
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pandas as pd
import json
import heapq

from .events import CorporateAction, Quote

COLUMNS = ["last", "bid1", "ask1", "iopv"]


def exchange_of(code: str) -> str:
    return "SH" if code.startswith(("5", "6")) else "SZ"


def normalize_symbol(code: str) -> str:
    code = code.split(".")[0]
    return f"{code}.{exchange_of(code)}"


def write_quotes(data_dir: Path, symbol: str, name: str, frame: pd.DataFrame) -> Path:
    path = Path(data_dir) / symbol / f"{name}.pkl"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[COLUMNS].astype("float32").sort_index().to_pickle(path)
    return path


def read_symbol(data_dir: Path, symbol: str, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
    files = sorted((Path(data_dir) / symbol).glob("*.pkl"))
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.concat([pd.read_pickle(f) for f in files]).astype("float64")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    if start is not None:
        frame = frame[frame.index >= start]
    if end is not None:
        frame = frame[frame.index < end]
    return frame


def iter_quotes(data_dir: Path, symbols: list[str], start: datetime | None = None,
                end: datetime | None = None) -> Iterator[tuple[datetime, list[Quote]]]:
    """按时间顺序产出同一时刻的一批报价。"""
    if list(Path(data_dir).glob("events_*.jsonl")):
        for kind, t, quotes in iter_events(data_dir, symbols, start, end):
            if kind == "quotes":
                yield t, quotes
        return
    parts = []
    for s in symbols:
        f = read_symbol(data_dir, s, start, end)
        if not f.empty:
            parts.append(f.assign(symbol=s))
    if not parts:
        return
    allq = pd.concat(parts).sort_index(kind="stable")
    times = allq.index.to_numpy()
    sym = allq.symbol.to_numpy()
    last, bid, ask, iopv = (allq[c].to_numpy() for c in COLUMNS)
    i, n = 0, len(allq)
    while i < n:
        j = i
        t = times[i]
        batch = []
        while j < n and times[j] == t:
            iv = float(iopv[j])
            batch.append(Quote(sym[j], pd.Timestamp(t).to_pydatetime(), round(float(last[j]), 3), round(float(bid[j]), 3),
                               round(float(ask[j]), 3), iv if iv > 0 else None, interval_end=True))
            j += 1
        yield batch[0].time, batch
        i = j


def iter_events(data_dir, symbols, start=None, end=None):
    """录制文件按原始批次和时钟回放；旧分钟采样文件仅供历史行情输入。"""
    files = sorted(Path(data_dir).glob("events_*.jsonl"))
    if not files:
        for t, quotes in iter_quotes(data_dir, symbols, start, end):
            yield "quotes", t, quotes
        return
    def stream(path):
        with path.open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = datetime.fromisoformat(r["time"])
                if (start is None or t >= start) and (end is None or t < end):
                    yield t, path.name, r["seq"], r
    for t, _, _, r in heapq.merge(*(stream(path) for path in files), key=lambda x: x[:3]):
        quotes = []
        for item in r["quotes"]:
            if item["symbol"] in symbols:
                item = dict(item)
                item["time"] = datetime.fromisoformat(item["time"])
                quotes.append(Quote(**item))
        yield r["kind"], t, quotes


def load_actions(data_dir: Path) -> list[CorporateAction]:
    path = Path(data_dir) / "corporate_actions.csv"
    if not path.exists():
        return []
    t = pd.read_csv(path, parse_dates=["date"], dtype={"symbol": str})
    return [CorporateAction(r.date.to_pydatetime(), r.symbol, float(r.cash_per_share), float(r.split_ratio))
            for r in t.itertuples()]
