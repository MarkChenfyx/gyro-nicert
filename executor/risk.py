"""下单前风控与暂停开关。任何一项不通过就拒绝该笔委托，并记录原因。

- 停止文件：存在 <stop_file> 时拒绝所有新委托（撤单不受影响）。
- 价格保护：限价偏离中间价超过 band_pct 拒绝。
- 单笔金额上限、每个策略每日换仓次数上限。
- 策略级熔断：当日权益回撤超过 max_daily_loss_pct 后该策略暂停至次日。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from math import isfinite

from .events import Order


@dataclass
class RiskConfig:
    stop_file: str = ""
    band_pct: float = 1.0
    max_order_value: float = 1_000_000.0
    max_intents_per_day: int = 20
    max_daily_loss_pct: float = 15.0


@dataclass
class RiskManager:
    cfg: RiskConfig
    _intents_today: dict[str, int] = field(default_factory=dict)
    _halted: dict[str, str] = field(default_factory=dict)
    _day: date | None = None
    _day_start_equity: dict[str, float] = field(default_factory=dict)

    def new_day(self, d: date, equities: dict[str, float]) -> None:
        if d != self._day:
            self._day = d
            self._intents_today.clear()
            self._halted.clear()
            self._day_start_equity = dict(equities)

    def stopped(self) -> bool:
        return bool(self.cfg.stop_file) and Path(self.cfg.stop_file).exists()

    def halted(self, strategy: str) -> str | None:
        return self._halted.get(strategy)

    def check_equity(self, strategy: str, equity: float) -> None:
        start = self._day_start_equity.get(strategy)
        if start and equity < start * (1 - self.cfg.max_daily_loss_pct / 100):
            self._halted.setdefault(strategy, f"当日回撤超过 {self.cfg.max_daily_loss_pct}%")

    def allow_intent(self, strategy: str) -> str | None:
        if self.stopped():
            return "停止文件存在"
        if strategy in self._halted:
            return self._halted[strategy]
        if self._intents_today.get(strategy, 0) >= self.cfg.max_intents_per_day:
            return "当日换仓次数已达上限"
        self._intents_today[strategy] = self._intents_today.get(strategy, 0) + 1
        return None

    def check_order(self, order: Order, mid: float | None, odd_lot_close: bool = False) -> str | None:
        if self.stopped():
            return "停止文件存在"
        if order.strategy in self._halted:
            return self._halted[order.strategy]
        if not isfinite(order.price) or order.price <= 0:
            return "委托价格无效"
        if order.volume <= 0 or (order.volume % 100 and not odd_lot_close):
            return "数量必须为 100 份的正整数倍"
        if mid is None or mid <= 0:
            return "没有有效行情"
        if abs(order.price / mid - 1) * 100 > self.cfg.band_pct:
            return f"限价偏离中间价超过 {self.cfg.band_pct}%"
        if order.price * order.volume > self.cfg.max_order_value:
            return "单笔金额超过上限"
        return None

    def state(self) -> dict:
        return {"day": self._day.isoformat() if self._day else None, "intents": self._intents_today,
                "halted": self._halted, "equities": self._day_start_equity}

    def restore(self, state: dict) -> None:
        self._day = date.fromisoformat(state["day"]) if state.get("day") else None
        self._intents_today = dict(state.get("intents", {}))
        self._halted = dict(state.get("halted", {}))
        self._day_start_equity = dict(state.get("equities", {}))
