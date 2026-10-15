"""同指数 ETF 轮动：同一指数的几只 ETF 中，始终持有相对自身常态最便宜的那只。

每个决策时点：
  溢价 = 中间价 / IOPV − 1（%）
  z    = 当前溢价 − 本 ETF 过去 lookback_days 天（各决策时点）溢价的中位数（不含当前）
  最便宜那只的 z 比持有那只低 threshold 个点以上 → 目标持仓改为最便宜那只（预算内 100%）。
未持仓且历史足够时，买入当前最便宜的那只。任一标的数据过期、历史不足、或还有未完成的换仓时不动作。
"""
from __future__ import annotations

from collections import deque
from statistics import median

from ..clock import AFTERNOON_FIRST, MORNING_FIRST
from ..events import Snapshot, TargetIntent
from .base import Context, Strategy


def slots_per_day(step: int) -> int:
    return (11 * 60 + 30 - MORNING_FIRST) // step + 1 + (14 * 60 + 56 - AFTERNOON_FIRST) // step + 1


class SameIndexRotation(Strategy):
    def __init__(self, name: str, symbols: list[str], threshold: float, lookback_days: int = 20, min_days: int = 10,
                 step_minutes: int = 5, ttl_seconds: float = 300.0, max_slip_ticks: int = 1):
        super().__init__()
        self.name, self.symbols = name, list(symbols)
        self.threshold, self.step_minutes = threshold, step_minutes
        self.ttl_seconds, self.max_slip_ticks = ttl_seconds, max_slip_ticks
        per_day = slots_per_day(step_minutes)
        self.window, self.min_samples = lookback_days * per_day, min_days * per_day
        self.history: dict[str, deque] = {s: deque(maxlen=self.window) for s in self.symbols}

    def on_snapshot(self, ctx: Context, snap: Snapshot) -> TargetIntent | None:
        z: dict[str, float] = {}
        prem: dict[str, float] = {}
        for s in self.symbols:
            if s in snap.stale:
                continue
            p = snap.quotes[s].premium
            prem[s] = p
            h = self.history[s]
            if len(h) >= self.min_samples:
                z[s] = p - median(h)
        for s, p in prem.items():                 # 先算 z 再记入历史：中位数不含当前
            self.history[s].append(p)

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

    def state(self) -> dict:
        return {"history": {s: list(h) for s, h in self.history.items()}}

    def restore(self, state: dict) -> None:
        for s, values in state.get("history", {}).items():
            if s in self.history:
                self.history[s] = deque(values, maxlen=self.window)
