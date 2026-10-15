"""模拟撮合：按盘口成交，回测和纸面模式共用。

撮合规则（保守）：
- 委托在报出后 latency 秒才可能成交；撤单同样在 latency 秒后生效。
- 买单：限价 ≥ 当时卖一 → 按卖一成交；卖单：限价 ≤ 当时买一 → 按买一成交。不考虑盘口深度（第一档量足够）。
- fill_ratio < 1 时每次只成交剩余数量的一部分（取整到 100 份），用来测试部分成交。
- reject_rate 按固定随机种子随机拒单，用来测试拒单处理。
- 买入检查资金，卖出检查可卖数量（T+1 标的当天买入的不能卖）；不满足则拒单。
- 手续费 = max(成交金额 × commission_bp / 10000, min_fee)。
- 除权除息在新交易日第一批行情前处理：现金分红记入资金，拆分按比例调整份额。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..events import CorporateAction, Order, OrderStatus, OrderUpdate, Quote, Side, Trade
from .base import MarketGateway, TradeGateway


@dataclass
class _Pending:
    order: Order
    eligible: datetime
    filled: int = 0
    amount: float = 0.0
    cancel_at: datetime | None = None


class SimBroker(TradeGateway):
    def __init__(self, clock, cash: float, latency_seconds: float = 0.0, commission_bp: float = 1.0, min_fee: float = 0.0,
                 fill_ratio: float = 1.0, reject_rate: float = 0.0, seed: int = 0, tplus1: set[str] | None = None,
                 actions: list[CorporateAction] | None = None):
        self.clock = clock
        self.cash = cash
        self.positions: dict[str, int] = {}
        self.bought_today: dict[str, int] = {}
        self.latency = timedelta(seconds=latency_seconds)
        self.commission_bp, self.min_fee = commission_bp, min_fee
        self.fill_ratio, self.reject_rate = fill_ratio, reject_rate
        self.rng = random.Random(seed)
        self.tplus1 = tplus1 or set()
        self.quotes: dict[str, Quote] = {}
        self.pending: dict[str, _Pending] = {}
        self._trade_seq = 0
        self._day: date | None = None
        self._actions: dict[date, list[CorporateAction]] = {}
        for a in actions or []:
            self._actions.setdefault(a.date.date(), []).append(a)
        self.sink = lambda event: None

    # ---- 交易接口 ----
    def send_order(self, order: Order) -> None:
        now = self.clock.now()
        if self.reject_rate and self.rng.random() < self.reject_rate:
            self.sink(OrderUpdate(order.client_id, OrderStatus.REJECTED, 0, 0.0, now, reason="模拟随机拒单"))
            return
        self.pending[order.client_id] = _Pending(order, now + self.latency)
        self.sink(OrderUpdate(order.client_id, OrderStatus.SUBMITTED, 0, 0.0, now, broker_id=f"SIM{len(self.pending)}"))

    def cancel_order(self, order: Order) -> None:
        p = self.pending.get(order.client_id)
        if p is not None and p.cancel_at is None:
            p.cancel_at = self.clock.now() + self.latency

    def query_positions(self) -> dict[str, int]:
        return {s: q for s, q in self.positions.items() if q}

    def query_cash(self) -> float:
        return self.cash

    # ---- 行情驱动撮合 ----
    def on_quotes(self, t: datetime, quotes: list[Quote]) -> None:
        if self._day != t.date():
            self._day = t.date()
            self.bought_today.clear()
            for a in self._actions.get(self._day, []):
                q = self.positions.get(a.symbol, 0)
                if q:
                    self.cash += q * a.cash_per_share
                    if a.split_ratio != 1.0:
                        self.positions[a.symbol] = int(round(q * a.split_ratio))
        for q in quotes:
            self.quotes[q.symbol] = q
        self.match(t)

    def match(self, t: datetime) -> None:
        for cid in list(self.pending):
            p = self.pending[cid]
            o = p.order
            if p.cancel_at is not None and t >= p.cancel_at:
                self._finish(p, OrderStatus.CANCELLED, t)
                continue
            if t < p.eligible:
                continue
            q = self.quotes.get(o.symbol)
            if q is None or not q.valid:
                continue
            remaining = o.volume - p.filled
            if o.side is Side.BUY and o.price >= q.ask:
                price = q.ask
            elif o.side is Side.SELL and o.price <= q.bid:
                price = q.bid
            else:
                continue
            qty = remaining if self.fill_ratio >= 1 else max(100, int(remaining * self.fill_ratio) // 100 * 100)
            qty = min(qty, remaining)
            fee = max(price * qty * self.commission_bp / 1e4, self.min_fee)
            if o.side is Side.BUY:
                if self.cash < price * qty + fee:
                    self._finish(p, OrderStatus.REJECTED, t, "资金不足")
                    continue
                self.cash -= price * qty + fee
                self.positions[o.symbol] = self.positions.get(o.symbol, 0) + qty
                self.bought_today[o.symbol] = self.bought_today.get(o.symbol, 0) + qty
            else:
                held = self.positions.get(o.symbol, 0)
                sellable = held - (self.bought_today.get(o.symbol, 0) if o.symbol in self.tplus1 else 0)
                if sellable < qty:
                    self._finish(p, OrderStatus.REJECTED, t, "可卖数量不足")
                    continue
                self.cash += price * qty - fee
                self.positions[o.symbol] = held - qty
            p.filled += qty
            p.amount += price * qty
            self._trade_seq += 1
            self.sink(Trade(f"SIMT{self._trade_seq}", cid, o.symbol, o.side, price, qty, t, fee))
            status = OrderStatus.FILLED if p.filled >= o.volume else OrderStatus.PARTIAL
            self.sink(OrderUpdate(cid, status, p.filled, p.amount / p.filled, t))
            if status is OrderStatus.FILLED:
                del self.pending[cid]

    def _finish(self, p: _Pending, status: OrderStatus, t: datetime, reason: str = "") -> None:
        avg = p.amount / p.filled if p.filled else 0.0
        self.sink(OrderUpdate(p.order.client_id, status, p.filled, avg, t, reason=reason))
        del self.pending[p.order.client_id]


class ReplayMarket(MarketGateway):
    """回测用行情源：由运行器逐批推入历史报价。"""

    def __init__(self):
        self.sink = lambda event: None
        self.symbols: list[str] = []

    def subscribe(self, symbols: list[str]) -> None:
        self.symbols = sorted(set(self.symbols) | set(symbols))
