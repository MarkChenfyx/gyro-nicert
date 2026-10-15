"""委托管理：生成唯一的客户端委托号、维护委托状态、成交去重。

状态只能按合法方向推进；迟到的旧回报（累计成交变少）会被忽略。
"""
from __future__ import annotations

from datetime import datetime

from .events import Order, OrderStatus, OrderUpdate, Side, Trade

FINAL = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}


class OrderManager:
    def __init__(self):
        self.orders: dict[str, Order] = {}
        self._seen_trades: set[str] = set()
        self._seq = 0

    def create(self, strategy: str, intent_id: str, symbol: str, side: Side, price: float, volume: int,
               now: datetime) -> Order:
        self._seq += 1
        cid = f"{strategy}|{intent_id}|{self._seq}"
        order = Order(cid, strategy, intent_id, symbol, side, round(price, 3), int(volume), now, updated=now)
        self.orders[cid] = order
        return order

    def active(self, strategy: str | None = None, intent_id: str | None = None) -> list[Order]:
        return [o for o in self.orders.values() if o.status.active
                and (strategy is None or o.strategy == strategy) and (intent_id is None or o.intent_id == intent_id)]

    def apply_update(self, u: OrderUpdate) -> Order | None:
        o = self.orders.get(u.client_id)
        if o is None or o.status in FINAL:
            return None
        if u.filled < o.filled:
            return None
        o.filled, o.avg_price, o.updated = u.filled, u.avg_price or o.avg_price, u.time
        o.broker_id = u.broker_id or o.broker_id
        o.reason = u.reason or o.reason
        if o.status is OrderStatus.CANCELLING and u.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL):
            return o                                  # 撤单进行中，保持撤单中状态
        o.status = u.status
        return o

    def accept_trade(self, t: Trade) -> Order | None:
        """返回成交所属委托；重复成交或未知委托返回 None。"""
        if t.trade_id in self._seen_trades:
            return None
        self._seen_trades.add(t.trade_id)
        return self.orders.get(t.client_id)

    def restore(self, orders: list[Order], trade_ids: set[str]) -> None:
        for o in orders:
            self.orders[o.client_id] = o
        self._seen_trades |= trade_ids
        self._seq = max([int(o.client_id.rsplit("|", 1)[-1]) for o in orders] + [self._seq])
