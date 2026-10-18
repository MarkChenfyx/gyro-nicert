from datetime import datetime, timedelta

import pandas as pd
import pytest

from executor.clock import DecisionScheduler, SimClock, decision_slot
from executor.data import iter_quotes, write_quotes
from executor.engine import Engine
from executor.events import Order, OrderStatus, OrderUpdate, Quote, Side, TargetIntent, Trade
from executor.gateways.sim import ReplayMarket, SimBroker
from executor.oms import OrderManager
from executor.risk import RiskConfig, RiskManager
from executor.store import Store
from executor.strategies.base import Context
from executor.strategies.same_index_rotation import SameIndexRotation

A, B = "513001.SH", "513002.SH"


def q(sym, t, price, prem=0.0):
    return Quote(sym, t, price, round(price - 0.001, 3), round(price + 0.001, 3), price / (1 + prem / 100))


# ---- 时钟 ----
def test_decision_slots_align_with_minute_snapshots():
    sch = DecisionScheduler(5)
    fired = [m for m in range(9 * 60 + 30, 11 * 60 + 31) if sch.due(datetime(2026, 1, 5, m // 60, m % 60))]
    assert fired[0] == 9 * 60 + 31 and fired[1] == 9 * 60 + 36 and len(fired) == 24
    assert decision_slot(datetime(2026, 1, 5, 14, 57), 5) is None
    assert decision_slot(datetime(2026, 1, 5, 12, 0), 5) is None


# ---- 模拟撮合 ----
def _broker(cash=100_000, **kw):
    clock = SimClock(datetime(2026, 1, 5, 9, 31))
    b = SimBroker(clock, cash, **kw)
    events = []
    b.sink = events.append
    return clock, b, events


def test_sim_fills_at_quote_after_latency_and_respects_tplus1():
    clock, b, ev = _broker(latency_seconds=60, tplus1={A})
    t0 = clock.now()
    b.on_quotes(t0, [q(A, t0, 1.000)])
    buy = Order("c1", "s", "i", A, Side.BUY, 1.001, 1000, t0)
    b.send_order(buy)
    b.match(t0)
    assert not [e for e in ev if isinstance(e, Trade)]                  # 延迟未到不成交
    t1 = t0 + timedelta(minutes=1)
    clock.set(t1)
    b.on_quotes(t1, [q(A, t1, 1.000)])
    trades = [e for e in ev if isinstance(e, Trade)]
    assert len(trades) == 1 and trades[0].price == 1.001 and b.positions[A] == 1000
    sell = Order("c2", "s", "i", A, Side.SELL, 0.999, 1000, t1)
    b.send_order(sell)
    clock.set(t1 + timedelta(minutes=2))
    b.on_quotes(clock.now(), [q(A, clock.now(), 1.000)])
    assert [e for e in ev if isinstance(e, OrderUpdate) and e.client_id == "c2"][-1].status is OrderStatus.REJECTED


def test_sim_partial_fill_and_cancel():
    clock, b, ev = _broker(fill_ratio=0.5)
    t0 = clock.now()
    b.on_quotes(t0, [q(A, t0, 1.0)])
    o = Order("c1", "s", "i", A, Side.BUY, 1.001, 1000, t0)
    b.send_order(o)
    b.match(t0)
    assert A not in b.positions                     # 下单不能消耗用于产生信号的旧报价
    clock.set(t0 + timedelta(seconds=1))
    b.on_quotes(clock.now(), [q(A, clock.now(), 1.0)])
    assert b.positions[A] == 500
    b.cancel_order(o)
    b.match(clock.now())
    last = [e for e in ev if isinstance(e, OrderUpdate)][-1]
    assert last.status is OrderStatus.CANCELLED and last.filled == 500


# ---- 委托管理 ----
def test_oms_ignores_stale_updates_and_duplicate_trades():
    oms = OrderManager()
    t = datetime(2026, 1, 5, 10)
    o = oms.create("s", "i", A, Side.BUY, 1.0, 1000, t)
    oms.apply_update(OrderUpdate(o.client_id, OrderStatus.PARTIAL, 600, 1.0, t))
    assert oms.apply_update(OrderUpdate(o.client_id, OrderStatus.SUBMITTED, 0, 0.0, t)) is None
    assert o.filled == 600
    tr = Trade("T1", o.client_id, A, Side.BUY, 1.0, 600, t)
    assert oms.accept_trade(tr) is o and oms.accept_trade(tr) is None


# ---- 风控 ----
def test_risk_blocks_on_stop_file_and_price_band(tmp_path):
    r = RiskManager(RiskConfig(stop_file=str(tmp_path / "STOP"), band_pct=1.0))
    o = Order("c", "s", "i", A, Side.BUY, 1.02, 1000, datetime(2026, 1, 5))
    assert "偏离" in r.check_order(o, 1.0)
    (tmp_path / "STOP").write_text("")
    assert r.check_order(o, 1.02) == "停止文件存在"
    assert r.allow_intent("s") == "停止文件存在"


# ---- 策略 ----
def _feed(strategy, snaps, book):
    out = []
    for s in snaps:
        intent = strategy.on_snapshot(Context(s.time, book, False), s)
        out.append(None if intent is None else intent.targets)
    return out


def _snapshots(days=12):
    from executor.events import Snapshot
    snaps = []
    t = datetime(2026, 1, 5, 9, 31)
    for i in range(days * 48):
        pa = 0.3 if (i // 7) % 2 else -0.3                 # A 的溢价在 ±0.3 间交替，B 为 0
        snaps.append(Snapshot(t + timedelta(minutes=5 * i), {A: q(A, t, 1.0, pa), B: q(B, t, 1.0, 0.0)}))
    return snaps


def test_rotation_is_deterministic_and_state_roundtrips():
    from executor.portfolio import Book
    snaps = _snapshots()
    s1 = SameIndexRotation("r", [A, B], threshold=0.3, min_days=10)
    full = _feed(s1, snaps, Book("r", 1e5, 1e5))
    s2 = SameIndexRotation("r", [A, B], threshold=0.3, min_days=10)
    half = _feed(s2, snaps[:300], Book("r", 1e5, 1e5))
    s3 = SameIndexRotation("r", [A, B], threshold=0.3, min_days=10)
    s3.restore(s2.state())
    rest = _feed(s3, snaps[300:], Book("r", 1e5, 1e5))
    assert full == half + rest
    assert any(x is not None for x in full[480:])              # 预热 10 天后开始给出目标


# ---- 引擎端到端：先卖后买、重启恢复 ----
def _write_data(tmp_path, days=14):
    days_idx = pd.bdate_range("2026-01-05", periods=days)
    minutes = [9 * 60 + 31 + 5 * k for k in range(24)] + [13 * 60 + 1 + 5 * k for k in range(24)]
    idx = pd.DatetimeIndex([d + pd.Timedelta(minutes=m) for d in days_idx for m in minutes])
    rows = {A: [], B: []}
    for i, t in enumerate(idx):
        pa = 0.4 if (i // 9) % 2 else -0.4
        rows[A].append((1.0, 0.999, 1.001, 1.0 / (1 + pa / 100)))
        rows[B].append((1.0, 0.999, 1.001, 1.0))
    for s in (A, B):
        write_quotes(tmp_path, s, "x", pd.DataFrame(rows[s], index=idx, columns=["last", "bid1", "ask1", "iopv"]))
    return idx


def _engine(tmp_path, db_name):
    clock = SimClock()
    broker = SimBroker(clock, 100_000, commission_bp=1.0)
    strat = SameIndexRotation("r", [A, B], threshold=0.3, min_days=10)
    store = Store(tmp_path / db_name)
    eng = Engine(clock=clock, market_gw=ReplayMarket(), trade_gw=broker, strategies=[strat], capitals={"r": 100_000},
                 store=store, risk=RiskManager(RiskConfig()))
    return eng, broker, store


def test_engine_sells_before_buying_and_books_match_broker(tmp_path):
    _write_data(tmp_path)
    eng, broker, store = _engine(tmp_path, "a.sqlite")
    eng.start()
    for t, quotes in iter_quotes(tmp_path, [A, B]):
        eng.on_quotes(t, quotes)
    eng.finish()
    book = eng.ledger.books["r"]
    assert book.positions == broker.query_positions()
    assert abs(book.cash - broker.query_cash()) < 1e-6
    orders = store.load_orders()
    assert len(orders) > 4
    for intent_id in {o.intent_id for o in orders}:
        seq = sorted((o for o in orders if o.intent_id == intent_id and o.filled), key=lambda o: int(o.client_id.rsplit("|", 1)[1]))
        sides = [o.side for o in seq]
        assert sides == sorted(sides, key=lambda s: 0 if s is Side.SELL else 1)   # 同一意图内先卖后买


def test_engine_restart_resumes_identically(tmp_path):
    idx = _write_data(tmp_path)
    split = idx[len(idx) // 2 + 3]
    eng, broker, store = _engine(tmp_path, "full.sqlite")
    eng.start()
    for t, quotes in iter_quotes(tmp_path, [A, B]):
        eng.on_quotes(t, quotes)
    eng.finish()
    full = [(o.created, o.side, o.symbol, o.volume) for o in store.load_orders()]

    eng1, broker1, store1 = _engine(tmp_path, "part.sqlite")
    eng1.start()
    for t, quotes in iter_quotes(tmp_path, [A, B], end=split):
        eng1.on_quotes(t, quotes)
    eng1.finish()
    for strat in eng1.strategies.values():
        store1.save_state(split, strat.name, strat.state())
    for b in eng1.ledger.books.values():
        store1.save_book(split, b.to_dict())
    store1.commit()
    # 新进程：同一个数据库，同一个券商（持仓延续）
    eng2 = Engine(clock=SimClock(split - timedelta(minutes=1)), market_gw=ReplayMarket(), trade_gw=broker1,
                  strategies=[SameIndexRotation("r", [A, B], threshold=0.3, min_days=10)], capitals={"r": 100_000},
                  store=store1, risk=RiskManager(RiskConfig()))
    broker1.clock = eng2.clock
    assert eng2.start() == []
    for t, quotes in iter_quotes(tmp_path, [A, B], start=split):
        eng2.on_quotes(t, quotes)
    eng2.finish()
    resumed = [(o.created, o.side, o.symbol, o.volume) for o in store1.load_orders()]
    assert len(full) > 4 and any(c >= split for c, *_ in full)        # 重启前后都有交易
    assert sorted(resumed) == sorted(full)


def test_engine_blocks_trading_when_broker_has_less_than_book(tmp_path):
    _write_data(tmp_path)
    eng, broker, store = _engine(tmp_path, "c.sqlite")
    from executor.portfolio import Book
    store.save_book(datetime(2026, 1, 1), Book("r", 1e5, 0, {A: 1000}).to_dict())
    store.commit()
    problems = eng.start()
    assert problems and not eng.trading_enabled
