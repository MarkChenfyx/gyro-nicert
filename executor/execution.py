"""完整目标转换为冻结数量的调仓任务；已有任务和未入账成交全部结束前拒绝替换。"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from .events import OrderStatus, Side, TargetIntent

LOT = 100
TICK = 0.001
MAX_ATTEMPTS = 5
REPRICE_SECONDS = 30

@dataclass
class IntentRun:
    intent: TargetIntent
    expires: datetime
    quantities: dict[str, int]
    phase: str = "sell"
    attempts: dict[str, int] = field(default_factory=dict)

    def try_once(self, key):
        if self.attempts.get(key, 0) >= MAX_ATTEMPTS:
            return False
        self.attempts[key] = self.attempts.get(key, 0) + 1
        return True

class Executor:
    def __init__(self, engine):
        self.e = engine
        self.runs: dict[str, IntentRun] = {}
        self.seen: set[tuple[str, str]] = set()

    def active(self, strategy):
        run = self.runs.get(strategy)
        return bool(self.e.oms.active(strategy)) or (run is not None and run.phase in ("sell", "buy", "expiring"))

    def submit(self, intent, now):
        key = (intent.strategy, intent.intent_id)
        if self.active(intent.strategy) or key in self.seen:
            return False
        book = self.e.ledger.books[intent.strategy]
        equity = book.cash + sum(q * self.e.market.mid(s) for s, q in book.positions.items())
        quantities = {s: int(equity * w / ((self.e.market.latest[s].ask + intent.max_slip_ticks*TICK)
                      * (1+self.e.commission_bp/1e4)) / LOT) * LOT for s,w in intent.targets.items() if w > 0}
        self.runs[intent.strategy] = IntentRun(intent, intent.created + timedelta(seconds=intent.ttl_seconds), quantities)
        self.seen.add(key)
        self.e.store.event(now, "intent", intent.strategy, intent_id=intent.intent_id, targets=intent.targets,
                           quantities=quantities, reason=intent.reason)
        return True

    def step(self, now):
        changed = False
        for strategy, run in list(self.runs.items()):
            if run.phase in ("done", "expired"):
                continue
            active = self.e.oms.active(strategy)
            if now >= run.expires or run.phase == "expiring":
                run.phase = "expiring"
                for o in active:
                    if o.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL):
                        self.e.cancel(o)
                        changed = True
                if not self.e.oms.active(strategy):
                    self._finish(run, "expired", now)
                    changed = True
                continue
            if active:
                for o in active:
                    if o.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL) and (now-o.created).total_seconds() >= REPRICE_SECONDS:
                        self.e.cancel(o)
                        changed = True
                continue
            if not self.e.can_trade(strategy, now):
                continue
            book = self.e.ledger.books[strategy]
            if run.phase == "sell":
                excess = [(s, q - run.quantities.get(s, 0)) for s, q in book.positions.items() if q > run.quantities.get(s, 0)]
                if excess:
                    for s, qty in excess:
                        if not self.e.market.fresh(s, now):
                            continue
                        vol = min(qty, self.e.available_sellable(strategy, s))
                        if vol < book.qty(s) or run.quantities.get(s, 0):
                            vol = vol // LOT * LOT
                        quote = self.e.market.latest[s]
                        if vol > 0 and run.try_once("S" + s):
                            changed |= self.e.place(run.intent, s, Side.SELL, round(quote.bid-run.intent.max_slip_ticks*TICK, 3), vol, now)
                    continue
                run.phase = "buy"
                changed = True
            missing = False
            for s, target in run.quantities.items():
                need = target - book.qty(s)
                if need < LOT:
                    continue
                if not self.e.market.fresh(s, now):
                    missing = True
                    continue
                quote = self.e.market.latest[s]
                price = round(quote.ask + run.intent.max_slip_ticks*TICK, 3)
                affordable = int(self.e.available_cash(strategy) / (price*(1+self.e.commission_bp/1e4)) / LOT)*LOT
                vol = min(need//LOT*LOT, affordable)
                if vol > 0:
                    missing = True
                    if run.try_once("B" + s):
                        changed |= self.e.place(run.intent, s, Side.BUY, price, vol, now)
            if not missing and not self.e.oms.active(strategy):
                self._finish(run, "done", now)
                changed = True
        return changed

    def _finish(self, run, phase, now):
        run.phase = phase
        b = self.e.ledger.books[run.intent.strategy]
        self.e.store.event(now, "intent_"+phase, run.intent.strategy, intent_id=run.intent.intent_id,
                           positions=dict(b.positions), cash=round(b.cash, 2))

    def state(self):
        return {"seen": [list(x) for x in sorted(self.seen)], "runs": {s: asdict(r) for s, r in self.runs.items()}}

    def restore(self, state):
        self.seen = {tuple(x) for x in state.get("seen", [])}
        for s, r in state.get("runs", {}).items():
            intent = dict(r["intent"])
            intent["created"] = datetime.fromisoformat(intent["created"])
            self.runs[s] = IntentRun(TargetIntent(**intent), datetime.fromisoformat(r["expires"]), r["quantities"], r["phase"], r["attempts"])
