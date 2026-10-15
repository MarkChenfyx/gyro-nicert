"""行情缓存与决策快照：保存各标的最新报价，按决策时点生成快照并标记过期数据。"""
from __future__ import annotations

from datetime import datetime, timedelta

from .events import Quote, Snapshot


class MarketCache:
    def __init__(self, max_age_seconds: float = 90.0):
        self.max_age = timedelta(seconds=max_age_seconds)
        self.latest: dict[str, Quote] = {}

    def update(self, quote: Quote) -> None:
        old = self.latest.get(quote.symbol)
        if old is not None and quote.time < old.time:
            return                                   # 乱序推送，丢弃
        self.latest[quote.symbol] = quote

    def snapshot(self, symbols: list[str], t: datetime) -> Snapshot:
        quotes, stale = {}, set()
        for s in symbols:
            q = self.latest.get(s)
            if q is None:
                stale.add(s)
                continue
            quotes[s] = q
            if t - q.time > self.max_age or q.premium is None:
                stale.add(s)
        return Snapshot(t, quotes, stale)

    def mid(self, symbol: str) -> float | None:
        q = self.latest.get(symbol)
        return q.mid if q is not None and q.valid else None
