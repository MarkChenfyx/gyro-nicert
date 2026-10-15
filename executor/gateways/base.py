"""网关接口约定。行情和交易可以来自不同网关（纸面模式：行情来自 QMT，成交来自模拟撮合）。

网关通过 sink 回调把事件交给引擎：
  sink(("quotes", time, [Quote, ...]))   一批同一时刻的报价
  sink(OrderUpdate)                      委托状态变化（累计成交数量）
  sink(Trade)                            新增成交
实盘网关的回调来自其他线程，引擎用线程安全队列接收，主线程顺序处理。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..events import Order

Sink = Callable[[Any], None]


class MarketGateway(ABC):
    sink: Sink

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None: ...


class TradeGateway(ABC):
    sink: Sink

    @abstractmethod
    def send_order(self, order: Order) -> None: ...

    @abstractmethod
    def cancel_order(self, order: Order) -> None: ...

    @abstractmethod
    def query_positions(self) -> dict[str, int]: ...

    @abstractmethod
    def query_cash(self) -> float: ...

    def query_open_orders(self) -> dict[str, dict]:
        """client_id → {status, filled, avg_price}；用于重启后核对未完成委托。"""
        return {}
