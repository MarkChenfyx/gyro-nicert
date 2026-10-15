"""行情录制：每个标的每分钟保留最后一个快照，按天写入 <data_dir>/<代码>/<日期>.pkl，格式与回放一致。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .data import write_quotes
from .events import Quote


class Recorder:
    def __init__(self, data_dir: Path, flush_every: int = 300):
        self.data_dir = Path(data_dir)
        self.rows: dict[str, dict[datetime, tuple]] = {}
        self.flush_every, self._count = flush_every, 0

    def add(self, quotes: list[Quote]) -> None:
        for q in quotes:
            minute = (q.time.replace(second=0, microsecond=0) + pd.Timedelta(minutes=1)
                      if q.time.second or q.time.microsecond else q.time)
            self.rows.setdefault(q.symbol, {})[minute] = (q.last, q.bid, q.ask, q.iopv or 0.0)
        self._count += 1
        if self._count % self.flush_every == 0:
            self.flush()

    def flush(self) -> None:
        for symbol, rows in self.rows.items():
            if not rows:
                continue
            frame = pd.DataFrame.from_dict(rows, orient="index", columns=["last", "bid1", "ask1", "iopv"]).sort_index()
            for day, part in frame.groupby(frame.index.date):
                write_quotes(self.data_dir, symbol, f"rec_{day:%Y%m%d}", part)
