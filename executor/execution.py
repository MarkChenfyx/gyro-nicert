"""执行层：把目标持仓变成委托，并推进到完成或过期。

一个意图分两阶段：
  1. 卖出：目标以外（或超出目标）的持仓，按买一价 − max_slip_ticks 跳限价卖出（目标为 0 时零股一起卖）。
  2. 买入：卖单全部结束后，按卖一价 + max_slip_ticks 跳限价买入，数量取整到 100 份且不超过可用资金。
挂出 REPRICE_SECONDS 秒仍未全部成交的委托撤掉，按最新盘口重挂（同一标的最多 MAX_ATTEMPTS 次）。
过了有效期仍未完成：撤掉剩余委托，意图记为过期，留下的缺口由策略下次决策时重新判断。
每个策略同一时间只有一个进行中的意图；新意图到来时旧意图先过期。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .events import OrderStatus, Side, TargetIntent

LOT = 100
TICK = 0.001
MAX_ATTEMPTS = 5                  # 同一意图内同一标的同一方向最多下单次数（含追价重挂；防止被拒后反复重下）
REPRICE_SECONDS = 30              # 委托挂出超过这么久仍未全部成交，撤单后按最新盘口重挂


@dataclass
class IntentRun:
    intent: TargetIntent
    expires: datetime
    phase: str = "sell"          # sell → buy → done / expired
    attempts: dict | None = None

    def try_once(self, key: str) -> bool:
        self.attempts = self.attempts or {}
        if self.attempts.get(key, 0) >= MAX_ATTEMPTS:
            return False
        self.attempts[key] = self.attempts.get(key, 0) + 1
        return True


class Executor:
    def __init__(self, engine):
        self.e = engine
        self.runs: dict[str, IntentRun] = {}

    def active(self, strategy: str) -> bool:
        run = self.runs.get(strategy)
        return run is not None and run.phase in ("sell", "buy", "expiring")

    def submit(self, intent: TargetIntent, now: datetime) -> None:
        old = self.runs.get(intent.strategy)
        if old is not None and old.phase in ("sell", "buy"):
            old.phase = "expiring"
        self.runs[intent.strategy] = IntentRun(intent, now + timedelta(seconds=intent.ttl_seconds))
        self.e.store.event(now, "intent", intent.strategy, intent_id=intent.intent_id, targets=intent.targets, reason=intent.reason)

    def step(self, now: datetime) -> bool:
        """推进所有意图；有新委托或状态变化时返回 True。"""
        changed = False
        for strategy, run in list(self.runs.items()):
            if run.phase in ("done", "expired"):
                continue
            active = self.e.oms.active(strategy, run.intent.intent_id)
            if not active and run.phase in ("sell", "buy") and self._satisfied(run):
                self._finish(run, "done", now)
                changed = True
                continue
            if run.phase == "expiring" or now >= run.expires:
                for o in active:
                    if o.status is not OrderStatus.CANCELLING:
                        self.e.cancel(o)
                        changed = True
                if not self.e.oms.active(strategy, run.intent.intent_id):
                    self._finish(run, "expired", now)
                    changed = True
                continue
            if active:
                for o in active:
                    if o.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL) and (now - o.created).total_seconds() >= REPRICE_SECONDS:
                        self.e.cancel(o)
                        changed = True
                continue
            if run.phase == "sell":
                if self._place_sells(run, now):
                    changed = True
                else:
                    run.phase = "buy"
            if run.phase == "buy":
                if self._place_buys(run, now):
                    changed = True
                elif not self.e.oms.active(strategy, run.intent.intent_id):
                    self._finish(run, "done", now)
                    changed = True
        return changed

    # ---- 内部 ----
    def _satisfied(self, run: IntentRun) -> bool:
        """持仓已达到目标：没有该卖的，也没有还能买的。"""
        book = self.e.ledger.books[run.intent.strategy]
        equity = self._equity(book)
        for s, q in book.positions.items():
            mid = self.e.market.mid(s)
            if mid and q - self._target_qty(run, s, equity, mid) >= LOT:
                return False
            if mid and run.intent.targets.get(s, 0.0) == 0 and q > 0:
                return False
        fee_rate = self.e.commission_bp / 1e4
        for s, w in run.intent.targets.items():
            quote = self.e.market.latest.get(s)
            if w <= 0 or quote is None or not quote.valid:
                continue
            need = self._target_qty(run, s, equity, quote.mid) - book.qty(s)
            price = quote.ask + run.intent.max_slip_ticks * TICK
            if need >= LOT and book.cash >= price * LOT * (1 + fee_rate):
                return False
        return True

    def _target_qty(self, run: IntentRun, symbol: str, equity: float, price: float) -> int:
        w = run.intent.targets.get(symbol, 0.0)
        return int(equity * w / price / LOT) * LOT if w > 0 else 0

    def _equity(self, book) -> float:
        return book.cash + sum(q * (self.e.market.mid(s) or 0.0) for s, q in book.positions.items())

    def _place_sells(self, run: IntentRun, now: datetime) -> bool:
        book = self.e.ledger.books[run.intent.strategy]
        equity = self._equity(book)
        placed = False
        for s, q in list(book.positions.items()):
            quote = self.e.market.latest.get(s)
            if quote is None or not quote.valid:
                continue
            excess = q - self._target_qty(run, s, equity, quote.mid)
            sellable = book.sellable(s, s in self.e.tplus1)
            vol = min(excess, sellable)
            if run.intent.targets.get(s, 0.0) > 0 or vol < q:
                vol = vol // LOT * LOT           # 部分减仓按整手；清仓时零股一起卖
            price = round(quote.bid - run.intent.max_slip_ticks * TICK, 3)
            if vol > 0 and run.try_once("S" + s) and self.e.place(run.intent, s, Side.SELL, price, vol, now):
                placed = True
        return placed

    def _place_buys(self, run: IntentRun, now: datetime) -> bool:
        book = self.e.ledger.books[run.intent.strategy]
        equity = self._equity(book)
        placed = False
        for s, w in run.intent.targets.items():
            if w <= 0:
                continue
            quote = self.e.market.latest.get(s)
            if quote is None or not quote.valid:
                continue
            need = self._target_qty(run, s, equity, quote.mid) - book.qty(s)
            price = round(quote.ask + run.intent.max_slip_ticks * TICK, 3)
            fee_rate = self.e.commission_bp / 1e4
            affordable = int(book.cash / (price * (1 + fee_rate)) / LOT) * LOT
            vol = min(need // LOT * LOT, affordable)
            if vol > 0 and run.try_once("B" + s) and self.e.place(run.intent, s, Side.BUY, price, vol, now):
                placed = True
        return placed

    def _finish(self, run: IntentRun, phase: str, now: datetime) -> None:
        run.phase = phase
        book = self.e.ledger.books[run.intent.strategy]
        self.e.store.event(now, "intent_" + phase, run.intent.strategy, intent_id=run.intent.intent_id,
                           positions=dict(book.positions), cash=round(book.cash, 2))
