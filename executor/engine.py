"""引擎：单线程顺序处理所有事件。

行情批次 → 更新行情缓存 →（模拟撮合）→ 处理委托/成交回报 → 到决策时点调用策略 → 执行层推进意图 → 反复结算直到稳定。
成交回报先更新账本，再通知策略，保证策略在回调里看到的持仓已包含这笔成交。
实盘网关的回调来自其他线程，通过线程安全队列进入，由 run_live 的主循环按顺序处理。
"""
from __future__ import annotations

import queue
import time as _time
from datetime import date, datetime

from .clock import DecisionScheduler
from .events import CorporateAction, GatewayStatus, Order, OrderStatus, OrderUpdate, Quote, Side, TargetIntent, Trade
from .execution import Executor
from .gateways.base import MarketGateway, TradeGateway
from .gateways.sim import SimBroker
from .market import MarketCache
from .oms import OrderManager
from .portfolio import Ledger
from .risk import RiskManager
from .store import Store
from .strategies.base import Context, Strategy


class Engine:
    def __init__(self, *, clock, market_gw: MarketGateway, trade_gw: TradeGateway, strategies: list[Strategy],
                 capitals: dict[str, float], store: Store, risk: RiskManager, tplus1: set[str] | None = None,
                 commission_bp: float = 1.0, max_quote_age: float = 90.0, actions: list[CorporateAction] | None = None,
                 recorder=None, state_save_every: int = 0):
        self.clock, self.market_gw, self.trade_gw = clock, market_gw, trade_gw
        self.strategies = {s.name: s for s in strategies}
        self.capitals, self.store, self.risk = capitals, store, risk
        self.tplus1 = tplus1 or set()
        self.commission_bp = commission_bp
        self.market = MarketCache(max_quote_age)
        self.ledger = Ledger()
        self.oms = OrderManager()
        self.executor = Executor(self)
        self.recorder = recorder
        self.schedulers = {s.name: DecisionScheduler(s.step_minutes) for s in strategies}
        self.actions: dict[date, list[CorporateAction]] = {}
        for a in actions or []:
            self.actions.setdefault(a.date.date(), []).append(a)
        self.trading_enabled = False
        self.halt_reason = ""
        self.state_save_every = state_save_every
        self._decisions = 0
        self._day: date | None = None
        self._events: queue.Queue = queue.Queue()
        self._quotes: queue.Queue = queue.Queue()
        market_gw.sink = self.post
        trade_gw.sink = self.post

    # ---- 启动与恢复 ----
    def post(self, event) -> None:
        (self._quotes if isinstance(event, tuple) else self._events).put(event)

    def start(self) -> list[str]:
        books = {b["strategy"]: b for b in self.store.load_books()}
        states = self.store.load_states()
        from .portfolio import Book
        for name, cap in self.capitals.items():
            if name in books:
                self.ledger.books[name] = Book.from_dict(books[name])
            else:
                self.ledger.open(name, cap)
            if name in states:
                self.strategies[name].restore(states[name])
        self.oms.restore(self.store.load_orders(), self.store.trade_ids())
        self.market_gw.subscribe(sorted({s for st in self.strategies.values() for s in st.symbols}))
        problems = self.reconcile()
        self.trading_enabled = not problems
        self.halt_reason = "；".join(problems)
        self.store.event(self.clock.now(), "start", trading_enabled=self.trading_enabled, problems=problems)
        self.store.commit()
        return problems

    def reconcile(self) -> list[str]:
        """账本与券商核对：券商持仓不得少于本引擎账本（账户里可能还有其他来源的仓位）；未完成委托以券商为准。"""
        problems = []
        broker = self.trade_gw.query_positions()
        for s, q in self.ledger.total_positions().items():
            if broker.get(s, 0) < q:
                problems.append(f"{s} 券商持仓 {broker.get(s, 0)} 少于账本 {q}")
        open_at_broker = self.trade_gw.query_open_orders()
        for o in self.oms.active():
            info = open_at_broker.get(o.client_id)
            if info is None:
                problems.append(f"委托 {o.client_id} 状态未知（券商未找到），需人工核对")
        return problems

    # ---- 事件处理 ----
    def on_quotes(self, t: datetime, quotes: list[Quote]) -> None:
        if hasattr(self.clock, "set"):
            self.clock.set(t)
        if self._day != t.date():
            self._new_day(t)
        for q in quotes:
            self.market.update(q)
        if self.recorder is not None:
            self.recorder.add(quotes)
        if isinstance(self.trade_gw, SimBroker):
            self.trade_gw.on_quotes(t, quotes)
        self.drain()
        due = [name for name, sch in self.schedulers.items() if sch.due(t)]
        if due:
            self.decide(t, due)
        self.settle(t)

    def drain(self) -> int:
        n = 0
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return n
            n += 1
            if isinstance(ev, OrderUpdate):
                self.on_order_update(ev)
            elif isinstance(ev, Trade):
                self.on_trade(ev)
            elif isinstance(ev, GatewayStatus) and not ev.connected:
                self.trading_enabled = False
                self.halt_reason = ev.message
                self.store.event(ev.time, "gateway_down", message=ev.message)

    def settle(self, t: datetime) -> None:
        for _ in range(20):
            changed = self.executor.step(t)
            if isinstance(self.trade_gw, SimBroker):
                self.trade_gw.match(t)
            n = self.drain()
            if not changed and n == 0:
                break

    def on_order_update(self, u: OrderUpdate) -> None:
        o = self.oms.apply_update(u)
        if o is None:
            return
        self.store.order(o)
        if o.status is OrderStatus.REJECTED:
            self.store.event(u.time, "order_rejected", o.strategy, client_id=o.client_id, reason=o.reason)
        self.strategies[o.strategy].on_order(self._ctx(o.strategy, u.time), o)

    def on_trade(self, t: Trade) -> None:
        o = self.oms.accept_trade(t)
        if o is None:
            self.store.event(t.time, "unknown_or_duplicate_trade", trade_id=t.trade_id, client_id=t.client_id)
            return
        self.ledger.apply_trade(o.strategy, t)
        self.store.trade(o.strategy, t)
        self.store.save_book(t.time, self.ledger.books[o.strategy].to_dict())
        self.strategies[o.strategy].on_trade(self._ctx(o.strategy, t.time), t)

    # ---- 决策与下单 ----
    def _ctx(self, name: str, now: datetime) -> Context:
        return Context(now, self.ledger.books[name], self.executor.active(name))

    def decide(self, t: datetime, names: list[str]) -> None:
        for name in names:
            st = self.strategies[name]
            snap = self.market.snapshot(st.symbols, t)
            intent = st.on_snapshot(self._ctx(name, t), snap)
            self.store.decision(t, name, {**st.last_decision, "stale": sorted(snap.stale),
                                          "intent": intent.targets if intent else None})
            book = self.ledger.books[name]
            self.risk.check_equity(name, self._equity(book))
            if intent is not None:
                self._submit(intent, t)
            self._decisions += 1
            if self.state_save_every and self._decisions % self.state_save_every == 0:
                self.store.save_state(t, name, st.state())
                self.store.commit()

    def _submit(self, intent: TargetIntent, t: datetime) -> None:
        if not self.trading_enabled:
            self.store.event(t, "intent_blocked", intent.strategy, reason=self.halt_reason or "交易未启用")
            return
        reason = self.risk.allow_intent(intent.strategy)
        if reason:
            self.store.event(t, "intent_blocked", intent.strategy, reason=reason)
            return
        self.executor.submit(intent, t)

    def place(self, intent: TargetIntent, symbol: str, side: Side, price: float, volume: int, now: datetime) -> bool:
        o = self.oms.create(intent.strategy, intent.intent_id, symbol, side, price, volume, now)
        book = self.ledger.books[intent.strategy]
        odd_lot_close = side is Side.SELL and volume == book.qty(symbol)
        check = o if not odd_lot_close or volume % 100 == 0 else Order(**{**o.__dict__, "volume": max(100, volume // 100 * 100)})
        reason = self.risk.check_order(check, self.market.mid(symbol))
        if reason:
            o.status, o.reason = OrderStatus.REJECTED, reason
            self.store.order(o)
            self.store.event(now, "order_blocked", intent.strategy, client_id=o.client_id, reason=reason)
            return False
        self.store.order(o)
        self.trade_gw.send_order(o)
        return True

    def cancel(self, o: Order) -> None:
        o.status = OrderStatus.CANCELLING
        self.store.order(o)
        self.trade_gw.cancel_order(o)

    # ---- 日切 ----
    def _equity(self, book) -> float:
        return book.cash + sum(q * (self.market.mid(s) or 0.0) for s, q in book.positions.items())

    def _new_day(self, t: datetime) -> None:
        if self._day is not None:
            self.end_of_day(self._day)
        self._day = t.date()
        self.ledger.new_day(self._day)
        for a in self.actions.get(self._day, []):
            self.ledger.apply_action(a)
            self.store.event(t, "corporate_action", symbol=a.symbol, cash=a.cash_per_share, split=a.split_ratio)
        self.risk.new_day(self._day, {n: self._equity(b) for n, b in self.ledger.books.items()})

    def end_of_day(self, d: date) -> None:
        for name, st in self.strategies.items():
            book = self.ledger.books[name]
            self.store.save_state(datetime.combine(d, datetime.min.time()), name, st.state())
            self.store.save_book(datetime.combine(d, datetime.min.time()), book.to_dict())
            self.store.end_of_day(d, name, book.to_dict(), st.state(), self._equity(book))

    def finish(self) -> None:
        if self._day is not None:
            self.end_of_day(self._day)
        self.store.commit()

    # ---- 实盘主循环 ----
    def run_live(self, stop_check, heartbeat_seconds: float = 1.0) -> None:
        """实盘/纸面：网关线程把事件放进队列，这里顺序处理；每秒至少推进一次执行层（处理超时）。"""
        last_tick = 0.0
        while not stop_check():
            try:
                ev = self._quotes.get(timeout=heartbeat_seconds)
                batch = [ev]
                while True:
                    try:
                        batch.append(self._quotes.get_nowait())
                    except queue.Empty:
                        break
                for _, t, quotes in batch:
                    self.on_quotes(t, quotes)
            except queue.Empty:
                pass
            self.drain()
            if _time.monotonic() - last_tick >= heartbeat_seconds:
                self.settle(self.clock.now())
                self.store.commit()
                last_tick = _time.monotonic()
        self.finish()
