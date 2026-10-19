"""同指数 ETF 轮动：同一指数的几只 ETF 中，始终持有相对自身常态最便宜的那只。

每个决策时点先算每只的“贵贱”值 v（单位：百分点），两种口径：
  premium（溢价版）：v = 中间价 / IOPV − 1（%）；需要 IOPV。
  price（价格版）：  v = 100·ln(复权中间价) − 组内各只的平均；不需要 IOPV，除权由 on_corporate_action 调整。
  z = v − 本 ETF 过去 lookback_days 天（各决策时点）v 的中位数（不含当前）
  最便宜那只的 z 比持有那只低 threshold 个点以上 → 目标持仓改为最便宜那只（预算内 100%）。
未持仓且历史足够时，买入当前最便宜的那只。数据过期、历史不足、或还有未完成的换仓时不动作；
价格版要求组内各只同时有效（组内平均依赖全部标的）。
"""
from __future__ import annotations

from collections import deque
from math import log
from statistics import median

from ..clock import AFTERNOON_FIRST, MORNING_FIRST
from ..events import Snapshot, Subscription, TargetIntent
from .base import Context, Strategy

SIGNALS = ("premium", "price")


def slots_per_day(step: int) -> int:
    return (11 * 60 + 30 - MORNING_FIRST) // step + 1 + (14 * 60 + 56 - AFTERNOON_FIRST) // step + 1


class SameIndexRotation(Strategy):
    def __init__(self, name: str, symbols: list[str], threshold: float, lookback_days: int = 20, min_days: int = 10,
                 step_minutes: int = 5, ttl_seconds: float = 300.0, max_slip_ticks: int = 1, signal: str = "premium"):
        super().__init__()
        if signal not in SIGNALS:
            raise ValueError(f"signal 只能是 {SIGNALS}")
        self.name, self.symbols, self.signal = name, list(symbols), signal
        self.threshold, self.step_minutes = threshold, step_minutes
        self.ttl_seconds, self.max_slip_ticks = ttl_seconds, max_slip_ticks
        per_day = slots_per_day(step_minutes)
        self.window, self.min_samples = lookback_days * per_day, min_days * per_day
        self.min_days = min_days
        self.history: dict[str, deque] = {s: deque(maxlen=self.window) for s in self.symbols}
        self.offsets: dict[str, float] = {s: 0.0 for s in self.symbols}  # 价格版：累计复权的对数偏移

    def subscription(self) -> Subscription:
        return Subscription(tuple(self.symbols), require_iopv=self.signal == "premium")

    def _values(self, snap: Snapshot) -> dict[str, float]:
        if self.signal == "premium":
            return {s: snap.quotes[s].premium for s in self.symbols if s not in snap.stale}
        if any(s in snap.stale for s in self.symbols):
            return {}
        rel = {s: 100 * (log(snap.quotes[s].mid) + self.offsets[s]) for s in self.symbols}
        mean = sum(rel.values()) / len(rel)
        return {s: r - mean for s, r in rel.items()}

    def on_snapshot(self, ctx: Context, snap: Snapshot) -> TargetIntent | None:
        values = self._values(snap)
        z: dict[str, float] = {}
        for s, v in values.items():
            h = self.history[s]
            if len(h) >= self.min_samples:
                z[s] = v - median(h)
        for s, v in values.items():                 # 先算 z 再记入历史：中位数不含当前
            self.history[s].append(v)

        held = {s: q for s, q in ctx.book.positions.items() if s in self.symbols and q > 0}
        hold = max(held, key=held.get) if held else None
        self.last_decision = {"z": {s: round(v, 4) for s, v in z.items()}, "hold": hold, "action": "none"}
        if len(z) < len(self.symbols) or ctx.intent_active:
            self.last_decision["action"] = "skip:intent" if ctx.intent_active else "skip:data"
            return None
        target = min(z, key=z.get)
        if hold is None:
            reason = "建仓：买入当前最便宜的"
        elif target != hold and z[target] < z[hold] - self.threshold:
            reason = f"{target} 比 {hold} 便宜 {z[hold] - z[target]:.3f} 点"
        else:
            return None
        self.last_decision["action"] = f"target:{target}"
        return TargetIntent(self.name, f"{snap.time:%Y%m%d%H%M}", snap.time, {target: 1.0},
                            self.ttl_seconds, self.max_slip_ticks, reason)

    def on_corporate_action(self, ctx: Context, symbol: str, ratio: float) -> None:
        # 除权后价格整体乘以 ratio；加上 −ln(ratio) 让复权价连续。溢价版的 IOPV 同步除权，无需处理。
        if self.signal == "price" and symbol in self.offsets and ratio > 0:
            self.offsets[symbol] -= log(ratio)

    def status(self) -> str:
        per_day = slots_per_day(self.step_minutes)
        have = min(len(h) for h in self.history.values())
        if have < self.min_samples:
            return f"预热中 {have / per_day:.1f}/{self.min_days} 天，暂不交易"
        return f"上次决策：{self.last_decision.get('action', '无')}"

    def state(self) -> dict:
        return {"history": {s: list(h) for s, h in self.history.items()}, "offsets": dict(self.offsets)}

    def configuration(self) -> dict:
        return {**super().configuration(), "threshold": self.threshold, "window": self.window, "signal": self.signal,
                "min_samples": self.min_samples, "ttl_seconds": self.ttl_seconds, "max_slip_ticks": self.max_slip_ticks}

    def restore(self, state: dict) -> None:
        for s, values in state.get("history", {}).items():
            if s in self.history:
                self.history[s] = deque(values, maxlen=self.window)
        for s, value in state.get("offsets", {}).items():
            if s in self.offsets:
                self.offsets[s] = float(value)
