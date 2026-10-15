"""QMT 网关（xtquant）。尚未在服务器上实测，字段名以 scripts/executor_probe_qmt.py 的实测输出为准再核对。

行情：xtdata.subscribe_whole_quote 推送全推行情（约 3 秒一次），转换为 Quote。IOPV 字段名未确认，按候选名依次尝试。
交易：XtQuantTrader + StockAccount；下单时把策略名填入 strategy_name，把引擎客户端委托号填入 order_remark，
     这样 QMT 的委托、成交记录和导出的 DBF 都直接带上策略归属。allow_orders=False 时任何下单/撤单都会被拒绝。
代码格式：引擎用 513530.SH / 159920.SZ，与 QMT 相同。
"""
from __future__ import annotations

import threading
import time as _time
from datetime import datetime

from ..events import GatewayStatus, Order, OrderStatus, OrderUpdate, Quote, Side, Trade
from .base import MarketGateway, TradeGateway

IOPV_KEYS = ("iopv", "IOPV", "iopvPrice", "fundIopv")

# xtconstant 委托状态 → 引擎状态
STATUS = {48: OrderStatus.PENDING, 49: OrderStatus.PENDING, 50: OrderStatus.SUBMITTED, 51: OrderStatus.CANCELLING,
          52: OrderStatus.CANCELLING, 53: OrderStatus.CANCELLED, 54: OrderStatus.CANCELLED, 55: OrderStatus.PARTIAL,
          56: OrderStatus.FILLED, 57: OrderStatus.REJECTED}


def _iopv(tick: dict) -> float | None:
    for k in IOPV_KEYS:
        v = tick.get(k)
        if v:
            return float(v)
    return None


def _ts(ms_or_s) -> datetime:
    v = float(ms_or_s)
    return datetime.fromtimestamp(v / 1000 if v > 1e11 else v)


class QmtGateway(MarketGateway, TradeGateway):
    def __init__(self, userdata_path: str, account_id: str, allow_orders: bool = False):
        self.userdata_path, self.account_id, self.allow_orders = userdata_path, account_id, allow_orders
        self.sink = lambda event: None
        self.trader = None
        self.account = None
        self._lock = threading.Lock()
        self._by_qmt_id: dict[int, str] = {}       # QMT 委托号 → 引擎客户端委托号
        self._client_orders: dict[str, Order] = {}

    # ---- 连接 ----
    def connect(self) -> None:
        from xtquant import xtconstant
        from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
        from xtquant.xttype import StockAccount

        gw = self
        self._xtconstant = xtconstant

        class Callback(XtQuantTraderCallback):
            def on_disconnected(self):
                gw.sink(GatewayStatus(datetime.now(), False, "QMT 交易连接断开"))

            def on_stock_order(self, order):
                gw._on_order(order)

            def on_stock_trade(self, trade):
                gw._on_trade(trade)

            def on_order_error(self, err):
                cid = gw._by_qmt_id.get(getattr(err, "order_id", -1), "")
                gw.sink(OrderUpdate(cid, OrderStatus.REJECTED, 0, 0.0, datetime.now(), reason=str(getattr(err, "error_msg", err))))

            def on_cancel_error(self, err):
                pass

        self.trader = XtQuantTrader(self.userdata_path, int(_time.time()))
        self.trader.register_callback(Callback())
        self.trader.start()
        if self.trader.connect() != 0:
            raise RuntimeError("连接 QMT 交易端失败：确认 QMT 已登录，userdata_path 正确")
        self.account = StockAccount(self.account_id)
        if self.trader.subscribe(self.account) != 0:
            raise RuntimeError("订阅资金账号失败")

    def close(self) -> None:
        if self.trader is not None:
            self.trader.stop()

    # ---- 行情 ----
    def subscribe(self, symbols: list[str]) -> None:
        from xtquant import xtdata

        def on_data(data: dict) -> None:
            quotes = []
            for code, tick in data.items():
                try:
                    bid = (tick.get("bidPrice") or [0])[0]
                    ask = (tick.get("askPrice") or [0])[0]
                    quotes.append(Quote(code, _ts(tick["time"]), round(float(tick.get("lastPrice", 0)), 3), round(float(bid), 3),
                                        round(float(ask), 3), _iopv(tick)))
                except (KeyError, TypeError, ValueError):
                    continue
            if quotes:
                self.sink(("quotes", max(q.time for q in quotes), quotes))

        xtdata.subscribe_whole_quote(list(symbols), callback=on_data)

    # ---- 交易 ----
    def send_order(self, order: Order) -> None:
        if not self.allow_orders:
            self.sink(OrderUpdate(order.client_id, OrderStatus.REJECTED, 0, 0.0, datetime.now(), reason="网关未允许下单"))
            return
        xc = self._xtconstant
        side = xc.STOCK_BUY if order.side is Side.BUY else xc.STOCK_SELL
        with self._lock:
            qmt_id = self.trader.order_stock(self.account, order.symbol, side, order.volume, xc.FIX_PRICE, order.price,
                                             order.strategy[:24], order.client_id[:48])
            if qmt_id is None or qmt_id < 0:
                self.sink(OrderUpdate(order.client_id, OrderStatus.REJECTED, 0, 0.0, datetime.now(), reason=f"下单失败 {qmt_id}"))
                return
            self._by_qmt_id[qmt_id] = order.client_id
            self._client_orders[order.client_id] = order
        self.sink(OrderUpdate(order.client_id, OrderStatus.SUBMITTED, 0, 0.0, datetime.now(), broker_id=str(qmt_id)))

    def cancel_order(self, order: Order) -> None:
        if not self.allow_orders or order.broker_id is None:
            return
        self.trader.cancel_order_stock(self.account, int(order.broker_id))

    def _cid(self, obj) -> str:
        cid = self._by_qmt_id.get(getattr(obj, "order_id", -1))
        return cid or str(getattr(obj, "order_remark", "") or "")

    def _on_order(self, o) -> None:
        cid = self._cid(o)
        if not cid:
            return
        status = STATUS.get(int(getattr(o, "order_status", 0)))
        if status is None:
            return
        self.sink(OrderUpdate(cid, status, int(getattr(o, "traded_volume", 0)), float(getattr(o, "traded_price", 0.0)),
                              datetime.now(), broker_id=str(getattr(o, "order_id", "")), reason=str(getattr(o, "status_msg", ""))))

    def _on_trade(self, t) -> None:
        cid = self._cid(t)
        order = self._client_orders.get(cid)
        if not cid or order is None:
            return
        self.sink(Trade(str(getattr(t, "traded_id", "")), cid, order.symbol, order.side, float(t.traded_price),
                        int(t.traded_volume), _ts(getattr(t, "traded_time", _time.time()))))

    def query_positions(self) -> dict[str, int]:
        rows = self.trader.query_stock_positions(self.account) or []
        return {p.stock_code: int(p.volume) for p in rows if int(p.volume) > 0}

    def query_cash(self) -> float:
        asset = self.trader.query_stock_asset(self.account)
        return float(asset.cash) if asset else 0.0

    def query_open_orders(self) -> dict[str, dict]:
        rows = self.trader.query_stock_orders(self.account, True) or []
        out = {}
        for o in rows:
            remark = str(getattr(o, "order_remark", "") or "")
            if remark:
                out[remark] = {"status": STATUS.get(int(o.order_status)), "filled": int(o.traded_volume)}
        return out
