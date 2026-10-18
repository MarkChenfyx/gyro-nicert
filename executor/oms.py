"""订单状态与逐笔入账分开管理；未知结果始终保留资源占用。"""
from __future__ import annotations
from datetime import datetime
from math import isfinite
from uuid import uuid4
from .events import Order, OrderStatus, OrderUpdate, Side, Trade

FINAL = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}

class OrderManager:
    def __init__(self):
        self.orders: dict[str, Order] = {}
        self._seen_trades: set[str] = set()
        self._seq = 0
        self.prefix = "g" + uuid4().hex[:10]

    def create(self, strategy, intent_id, symbol, side, price, volume, now):
        self._seq += 1
        cid = f"{self.prefix}|{self._seq}"
        if len(cid) > 24:
            raise ValueError("客户端编号超过 QMT 备注限制")
        o = Order(cid, strategy, intent_id, symbol, side, round(price, 3), int(volume), now, updated=now)
        self.orders[cid] = o
        return o

    def active(self, strategy=None, intent_id=None):
        return [o for o in self.orders.values() if o.unsettled
                and (strategy is None or o.strategy == strategy) and (intent_id is None or o.intent_id == intent_id)]

    def apply_update(self, u: OrderUpdate):
        o = self.orders.get(u.client_id)
        if o is None:
            return None
        if u.filled < 0 or u.filled > o.volume:
            raise ValueError("券商累计成交数量非法")
        if u.status is OrderStatus.FILLED and u.filled != o.volume:
            raise ValueError("全成状态与委托数量不一致")
        if u.filled < o.filled:
            return None
        if (o.status is u.status and o.filled == u.filled and (not u.broker_id or o.broker_id == u.broker_id)
                and (not u.reason or o.reason == u.reason)):
            return None
        if o.status in FINAL and u.status not in FINAL:
            return None
        o.filled = max(o.filled, u.filled, o.accounted)
        o.avg_price = u.avg_price or o.avg_price
        o.broker_id = u.broker_id or o.broker_id
        o.reason = u.reason or o.reason
        o.updated = u.time
        if o.accounted == o.volume:
            o.status = OrderStatus.FILLED
        elif o.status is OrderStatus.CANCELLING and u.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL):
            pass
        elif o.status not in FINAL or u.filled > o.accounted:
            o.status = u.status
        return o

    def accept_trade(self, t: Trade):
        if t.trade_id in self._seen_trades:
            return None
        o = self.orders.get(t.client_id)
        if o is None:
            return None
        if (not t.trade_id or t.symbol != o.symbol or t.side is not o.side or t.volume <= 0
                or not isfinite(t.price) or t.price <= 0 or not isfinite(t.fee) or t.fee < 0
                or o.accounted + t.volume > o.volume):
            raise ValueError("成交与本地委托不一致")
        self._seen_trades.add(t.trade_id)
        o.accounted += t.volume
        o.filled = max(o.filled, o.accounted)
        o.updated = t.time
        if o.accounted == o.volume:
            o.status = OrderStatus.FILLED
        return o

    def restore(self, orders, trade_ids, accounted=None):
        self.orders = {o.client_id: o for o in orders}
        self._seen_trades = set(trade_ids)
        for o in orders:
            o.accounted = (accounted or {}).get(o.client_id, o.accounted)
        self._seq = max([int(o.client_id.rsplit("|", 1)[-1]) for o in orders] + [self._seq])
