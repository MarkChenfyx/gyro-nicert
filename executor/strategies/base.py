"""策略接口。

约定：
- 策略不读系统时间、不调用网关、不保存文件；只用引擎给的时间、快照和只读账本。
- 同样的快照序列 + 同样的初始状态 → 同样的决策（确定性），这样实盘录下的数据可以每天重放核对。
- 会影响决策的内部状态都要能通过 state()/restore() 保存和恢复。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..events import Order, Snapshot, TargetIntent, Trade
from ..portfolio import Book


@dataclass(frozen=True)
class Context:
    now: datetime
    book: Book                    # 只读：本策略的资金和持仓
    intent_active: bool           # 是否还有未完成的交易意图


class Strategy(ABC):
    name: str
    symbols: list[str]
    step_minutes: int = 5

    def __init__(self):
        self.last_decision: dict[str, Any] = {}

    @abstractmethod
    def on_snapshot(self, ctx: Context, snap: Snapshot) -> TargetIntent | None: ...

    def on_order(self, ctx: Context, order: Order) -> None:
        pass

    def on_trade(self, ctx: Context, trade: Trade) -> None:
        pass

    def state(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass
