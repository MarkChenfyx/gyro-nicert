"""策略账本：每个策略只管自己的资金和持仓，不替代共用账户的资源协调。

可卖数量：T+1 标的当天买入的部分不可卖；T+0 标的全部可卖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .events import CorporateAction, Side, Trade


@dataclass
class Book:
    strategy: str
    capital: float
    cash: float
    positions: dict[str, int] = field(default_factory=dict)
    bought_today: dict[str, int] = field(default_factory=dict)
    fees: float = 0.0
    dividends: float = 0.0
    day: date | None = None

    def qty(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def sellable(self, symbol: str, tplus1: bool) -> int:
        q = self.qty(symbol)
        return q - self.bought_today.get(symbol, 0) if tplus1 else q

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices.get(s, 0.0) for s, q in self.positions.items())

    def to_dict(self) -> dict:
        return {"strategy": self.strategy, "capital": self.capital, "cash": self.cash, "positions": dict(self.positions),
                "bought_today": dict(self.bought_today), "fees": self.fees, "dividends": self.dividends,
                "day": self.day.isoformat() if self.day else None}

    @classmethod
    def from_dict(cls, d: dict) -> "Book":
        b = cls(d["strategy"], d["capital"], d["cash"], dict(d["positions"]), dict(d.get("bought_today", {})),
                d.get("fees", 0.0), d.get("dividends", 0.0))
        b.day = date.fromisoformat(d["day"]) if d.get("day") else None
        return b


class Ledger:
    def __init__(self):
        self.books: dict[str, Book] = {}

    def open(self, strategy: str, capital: float) -> Book:
        if strategy not in self.books:
            self.books[strategy] = Book(strategy, capital, capital)
        return self.books[strategy]

    def new_day(self, d: date) -> None:
        for b in self.books.values():
            if b.day != d:
                b.bought_today.clear()
                b.day = d

    def apply_trade(self, strategy: str, trade: Trade) -> None:
        b = self.books[strategy]
        if trade.side is Side.SELL and trade.volume > b.qty(trade.symbol):
            raise ValueError("卖出成交数量超过账本持仓")
        amount = trade.price * trade.volume
        if trade.side is Side.BUY:
            b.cash -= amount + trade.fee
            b.positions[trade.symbol] = b.qty(trade.symbol) + trade.volume
            b.bought_today[trade.symbol] = b.bought_today.get(trade.symbol, 0) + trade.volume
        else:
            b.cash += amount - trade.fee
            b.positions[trade.symbol] = b.qty(trade.symbol) - trade.volume
            if b.positions[trade.symbol] < 0:
                raise ValueError(f"{strategy} 卖出后持仓为负：{trade}")
            if b.positions[trade.symbol] == 0:
                del b.positions[trade.symbol]
        b.fees += trade.fee

    def apply_action(self, action: CorporateAction) -> None:
        for b in self.books.values():
            q = b.qty(action.symbol)
            if q == 0:
                continue
            if action.cash_per_share:
                cash = q * action.cash_per_share
                b.cash += cash
                b.dividends += cash
            if action.split_ratio != 1.0:
                b.positions[action.symbol] = int(round(q * action.split_ratio))

    def total_positions(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for b in self.books.values():
            for s, q in b.positions.items():
                total[s] = total.get(s, 0) + q
        return total


class UnitPerformance:
    """单位持仓盈亏/上期收盘价，逐期简单累加；份数按冻结目标的成交比例记录。"""
    def __init__(self):
        self.books = {}
        self.prices = {}
        self.references = {}

    def open(self, name):
        self.books.setdefault(name, {"units": {}, "daily": 0.0, "cumulative": 0.0, "valid": True, "complete": True})

    def new_day(self):
        self.references = dict(self.prices)
        for b in self.books.values():
            b["daily"] = 0.0
            b["valid"] = True

    def _add(self, name, symbol, pnl):
        ref = self.references.get(symbol)
        b = self.books[name]
        if not ref:
            if pnl:
                b["valid"] = False
                b["complete"] = False
            return
        value = pnl / ref * 100
        b["daily"] += value
        b["cumulative"] += value

    def mark(self, symbol, price):
        old = self.prices.get(symbol, price)
        for name, b in self.books.items():
            self._add(name, symbol, b["units"].get(symbol, 0.0) * (price-old))
        self.prices[symbol] = price

    def trade(self, name, trade, previous_qty, target_qty, target_weight):
        b = self.books[name]
        if trade.side is Side.BUY:
            units = trade.volume / target_qty * target_weight if target_qty else 0.0
            b["units"][trade.symbol] = b["units"].get(trade.symbol, 0.0) + units
            pnl = units * (self.prices.get(trade.symbol, trade.price)-trade.price)
        else:
            units = b["units"].get(trade.symbol, 0.0) * trade.volume / previous_qty if previous_qty else 0.0
            b["units"][trade.symbol] = max(0.0, b["units"].get(trade.symbol, 0.0)-units)
            pnl = units * (trade.price-self.prices.get(trade.symbol, trade.price))
        self._add(name, trade.symbol, pnl - units * trade.fee / trade.volume)

    def state(self):
        return {"books": self.books, "prices": self.prices, "references": self.references}

    def restore(self, state):
        self.books = state.get("books", {})
        self.prices = state.get("prices", {})
        self.references = state.get("references", {})
