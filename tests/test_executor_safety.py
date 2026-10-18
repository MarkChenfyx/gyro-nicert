"""执行器验收回归：崩溃、乱序、资源、数据分发和单位仓位口径。全部使用合成数据。"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import pytest
from executor.bars import BarGenerator
from executor.clock import SimClock
from executor.data import iter_events
from executor.engine import Engine
from executor.events import CancelError, GatewayStatus, OrderStatus, OrderUpdate, Quote, Side, Subscription, TargetIntent, Trade
from executor.gateways.base import TradeGateway
from executor.gateways.qmt import QmtMarketGateway, QmtTradeGateway
from executor.gateways.sim import ReplayMarket, SimBroker
from executor.oms import OrderManager
from executor.portfolio import UnitPerformance
from executor.recorder import Recorder
from executor.risk import RiskConfig, RiskManager
from executor.store import Store
from executor.strategies.base import Strategy

A,B="513001.SH","513002.SH"
T=datetime(2026,1,5,9,31)
def q(symbol=A,t=T,iopv=1,price=1):
    return Quote(symbol,t,price,price-.001,price+.001,iopv)

class Passive(Strategy):
    name="r"; symbols=[A,B]; step_minutes=5
    def on_snapshot(self,ctx,snap):
        self.last_decision={"action":"hold","iopv":{s:q.iopv for s,q in snap.quotes.items()}}

class ControlledBroker(TradeGateway):
    def __init__(self):
        self.sent=[]; self.updates={}; self.trades=[]; self.positions={}; self.cash=1000.; self.sink=lambda e:None
        self.before_send=None; self.fail_send=False
    def send_order(self,o):
        if self.before_send: self.before_send(o)
        if self.fail_send: raise ConnectionError("reply lost")
        self.sent.append(deepcopy(o))
        u=OrderUpdate(o.client_id,OrderStatus.SUBMITTED,0,0,o.created,broker_id=str(len(self.sent)))
        self.updates[o.client_id]=u; self.sink(u)
    def cancel_order(self,o):
        self.sink(CancelError(o.client_id,T,"cancel refused"))
    def query_positions(self): return dict(self.positions)
    def query_sellable_positions(self): return dict(self.positions)
    def query_cash(self): return self.cash
    def query_order_updates(self): return list(self.updates.values())
    def query_trades(self): return list(self.trades)

@pytest.fixture
def factory(tmp_path):
    opened=[]
    def make(name="a",broker=None,recorder=None,strategy=None,prime=True):
        broker=broker or ControlledBroker()
        store=Store(tmp_path/(name+".sqlite")); opened.append(store)
        e=Engine(clock=SimClock(T-timedelta(minutes=1)),market_gw=ReplayMarket(),trade_gw=broker,
            strategies=[strategy or Passive()],capitals={"r":1000},store=store,risk=RiskManager(RiskConfig()),recorder=recorder)
        assert e.start()==[]
        if prime and e.clock.now() <= T:
            e.clock.set(T)
            e.market.update(q(A)); e.market.update(q(B))
        return e,broker,store
    yield make
    for store in opened:
        try: store.close()
        except sqlite3.ProgrammingError: pass

def target(e,ident="i",weights=None):
    return e._submit(TargetIntent("r",ident,T,weights if weights is not None else {A:1},ttl_seconds=600),T)

def test_order_and_execution_are_committed_before_send(factory):
    e,b,store=factory()
    seen=[]
    def observe(o):
        with sqlite3.connect(store.path) as conn:
            seen.append(conn.execute("SELECT status FROM orders WHERE client_id=?",(o.client_id,)).fetchone()[0])
            state=json.loads(conn.execute("SELECT payload FROM runtime_state WHERE name='engine'").fetchone()[0])
            assert state["executor"]["runs"]["r"]["intent"]["intent_id"]=="i"
    b.before_send=observe
    assert target(e); e.settle(T)
    assert seen==["PENDING"]

def test_full_order_update_before_trade_does_not_resend(factory):
    e,b,store=factory(); target(e); e.settle(T)
    o=b.sent[0]
    e.on_order_update(OrderUpdate(o.client_id,OrderStatus.FILLED,o.volume,1.001,T))
    e.settle(T)
    assert len(b.sent)==1 and e.oms.active()[0].reserved==o.volume
    trade=Trade("fill",o.client_id,A,Side.BUY,1.001,o.volume,T)
    e.on_trade(trade); cash=e.ledger.books["r"].cash
    e.on_trade(trade); e.settle(T)
    assert e.ledger.books["r"].qty(A)==o.volume and e.ledger.books["r"].cash==cash
    assert len(b.sent)==1

def test_trade_first_then_late_order_reports_preserve_quantity(factory):
    e,b,_=factory(); target(e); e.settle(T); o=b.sent[0]
    e.on_trade(Trade("fill",o.client_id,A,Side.BUY,1.001,o.volume,T))
    e.on_order_update(OrderUpdate(o.client_id,OrderStatus.SUBMITTED,0,0,T))
    e.on_order_update(OrderUpdate(o.client_id,OrderStatus.FILLED,o.volume,1.001,T))
    assert e.oms.orders[o.client_id].accounted==o.volume
    assert not e.oms.active()

def test_uncertain_send_is_durable_and_not_retried(factory):
    e,b,st=factory(); b.fail_send=True
    target(e); e.settle(T)
    o=next(iter(e.oms.orders.values()))
    assert o.status is OrderStatus.UNKNOWN and not e.trading_enabled
    assert st.load_orders()[0].status is OrderStatus.UNKNOWN
    e.settle(T+timedelta(seconds=1)); assert len(e.oms.orders)==1

@pytest.mark.parametrize("halt",["disconnect","strategy","stop"])
def test_all_new_orders_obey_final_halt(factory,tmp_path,halt):
    e,b,_=factory(); target(e)
    if halt=="disconnect": e.post(GatewayStatus(T,False,"offline")); e.drain()
    elif halt=="strategy": e.risk._halted["r"]="halt"
    else:
        path=tmp_path/"STOP"; path.touch(); e.risk.cfg.stop_file=str(path)
    e.settle(T)
    assert not b.sent

def test_stale_or_outside_session_quote_cannot_execute(factory):
    e,b,_=factory(); target(e)
    e.settle(T+timedelta(seconds=120)); assert not b.sent
    e.market.update(q(A,T.replace(hour=12)))
    e.settle(T.replace(hour=12)); assert not b.sent

def test_multi_order_cash_reservation_and_zero_account_cash(factory):
    e,b,_=factory(); target(e,weights={A:.5,B:.5}); e.settle(T)
    assert len(b.sent)==2
    assert sum(o.volume*o.price*1.0001 for o in b.sent)<=1000
    e2,b2,_=factory("zero"); b2.cash=0; target(e2); e2.settle(T)
    assert not b2.sent

def test_replacing_active_or_repeating_intent_is_rejected(factory):
    e,b,_=factory(); assert target(e); e.settle(T)
    assert not target(e,"new") and not target(e)
    assert len(b.sent)==1 and e.executor.runs["r"].intent.intent_id=="i"

def test_real_restart_imports_missing_fill_and_preserves_active_target(factory):
    e,b,st=factory("restart"); target(e); e.settle(T); o=b.sent[0]
    st.close()  # 模拟进程退出；不调用 finish，也不额外补保存状态。
    b.positions[A]=500; b.cash-=500.5
    b.trades.append(Trade("missed",o.client_id,A,Side.BUY,1.001,500,T))
    b.updates[o.client_id]=OrderUpdate(o.client_id,OrderStatus.PARTIAL,500,1.001,T,broker_id="1")
    e2,b,_=factory("restart",broker=b)
    assert e2.ledger.books["r"].qty(A)==500
    assert e2.oms.orders[o.client_id].accounted==500
    assert e2._ctx("r",T).intent_active
    assert not target(e2,"new")
    e2.settle(T); assert len(b.sent)==1

def test_unknown_broker_order_blocks_restart(factory,tmp_path):
    e,b,st=factory("missing"); target(e); e.settle(T); st.close(); b.updates.clear()
    st2=Store(tmp_path/"missing.sqlite")
    e2=Engine(clock=SimClock(T),market_gw=ReplayMarket(),trade_gw=b,strategies=[Passive()],capitals={"r":1000},store=st2,risk=RiskManager(RiskConfig()))
    try:
        assert e2.start() and not e2.trading_enabled
        assert next(iter(e2.oms.orders.values())).status is OrderStatus.UNKNOWN
    finally: st2.close()

def test_cancel_failure_keeps_reservation_and_halts(factory):
    e,b,_=factory(); target(e); e.settle(T); o=e.oms.active()[0]
    e.cancel(o); e.drain()
    assert o.status is OrderStatus.UNKNOWN and o.reserved==o.volume and not e.trading_enabled

def test_qmt_short_id_restored_mapping_and_early_trade_callback():
    oms=OrderManager(); o=oms.create("rot_hk_dividend","202601050931",A,Side.BUY,1.001,100,T)
    assert len(o.client_id.encode("ascii"))<=24
    gw=QmtTradeGateway("","",True); events=[]; gw.sink=events.append
    gw._xtconstant=SimpleNamespace(STOCK_BUY=23,STOCK_SELL=24,FIX_PRICE=11)
    def send(*args):
        assert args[-1]==o.client_id
        gw._on_trade(SimpleNamespace(order_id=7,order_remark=o.client_id,traded_id="t1",traded_price=1.001,traded_volume=100,traded_time=1767576660))
        return 7
    gw.trader=SimpleNamespace(order_stock=send)
    gw.send_order(o)
    assert isinstance(events[0],Trade)
    fresh=QmtTradeGateway("",""); o.broker_id="7"; fresh.restore_orders([o]); got=[]; fresh.sink=got.append
    fresh._on_trade(SimpleNamespace(order_id=7,order_remark="",traded_id="t2",traded_price=1.001,traded_volume=100,traded_time=1767576660))
    assert len(got)==1 and got[0].client_id==o.client_id

def test_qmt_cancel_negative_result_emits_error():
    o=OrderManager().create("r","i",A,Side.BUY,1,100,T); o.broker_id="1"
    gw=QmtTradeGateway("","",True); gw.trader=SimpleNamespace(cancel_order_stock=lambda *_:-1); got=[]; gw.sink=got.append
    gw.cancel_order(o)
    assert isinstance(got[0],CancelError)

def test_recording_replay_uses_exact_complete_multisymbol_input(factory,tmp_path):
    data=tmp_path/"quotes"; e,_,st=factory("live",recorder=Recorder(data),prime=False)
    t=T-timedelta(seconds=57)
    e.on_quotes(t,[q(A,t)])
    e.on_quotes(t+timedelta(seconds=1),[q(B,t+timedelta(seconds=1))])
    e.on_quotes(T-timedelta(seconds=3),[q(A,T-timedelta(seconds=3),iopv=1.1)])
    assert not st.decisions_on(T.date())
    e.on_timer(T+timedelta(seconds=3))
    original=st.decisions_on(T.date())
    assert len(original)==1 and original[0][2]["stale"]==[]
    e2,_,st2=factory("replayed",prime=False)
    for kind,ts,qs in iter_events(data,[A,B]):
        e2.on_quotes(ts,qs) if kind=="quotes" else e2.on_timer(ts)
    assert original==st2.decisions_on(T.date())

def test_recording_restart_retains_previous_session(tmp_path):
    Recorder(tmp_path).add([q(A,T)])
    Recorder(tmp_path).add([q(A,T+timedelta(hours=1))])
    events=list(iter_events(tmp_path,[A]))
    assert len(events)==2 and events[0][1]==T and events[1][1]==T+timedelta(hours=1)

def test_partial_fill_requires_new_quote_and_paper_state_restores(factory):
    clock=SimClock(T-timedelta(minutes=1)); broker=SimBroker(clock,1000,fill_ratio=.5)
    e,_,st=factory("paper",broker=broker); broker.clock=e.clock
    e.on_quotes(T,[q(A),q(B)]); target(e); e.settle(T)
    assert not broker.positions
    e.on_quotes(T+timedelta(seconds=1),[q(A,T+timedelta(seconds=1))])
    qty=broker.positions[A]; assert qty==400
    for _ in range(5): e.settle(T+timedelta(seconds=1))
    assert broker.positions[A]==qty
    cash=broker.cash; st.close()
    fresh=SimBroker(SimClock(T-timedelta(minutes=1)),1000,fill_ratio=.5)
    e2,_,_=factory("paper",broker=fresh); fresh.clock=e2.clock
    assert fresh.positions[A]==qty and fresh.cash==cash and e2._ctx("r",T).intent_active

def test_quote_bars_are_closed_aligned_and_engine_distributes(factory):
    class Bars(Passive):
        def __init__(self): super().__init__(); self.got=[]
        def subscription(self): return Subscription((A,B),(1,),False)
        def on_bars(self,ctx,end,minutes,bars,missing): self.got.append((end,bars,missing))
    strat=Bars(); e,_,_=factory(strategy=strat,prime=False)
    t=T-timedelta(seconds=50)
    e.on_quotes(t,[q(A,t,price=1),q(B,t,price=2)])
    e.on_quotes(T-timedelta(seconds=1),[q(A,T-timedelta(seconds=1),price=1.1)])
    assert not strat.got
    e.on_timer(T+timedelta(seconds=3))
    assert len(strat.got)==1 and not strat.got[0][2]
    bar=strat.got[0][1][A]
    assert (bar.open,bar.high,bar.low,bar.close)==(1,1.1,1,1.1)
    assert bar.start==T-timedelta(minutes=1) and bar.end==T

def test_unit_returns_simple_sum_and_independent_of_capital():
    totals=[]
    for qty in (100,10000):
        p=UnitPerformance(); p.open("r"); p.mark(A,100); p.new_day()
        p.trade("r",Trade("t","o",A,Side.BUY,100,qty,T),0,qty,1)
        p.mark(A,110); assert p.books["r"]["daily"]==pytest.approx(10)
        p.new_day(); p.mark(A,121)
        assert p.books["r"]["daily"]==pytest.approx(10)
        totals.append(p.books["r"]["cumulative"])
    assert totals==pytest.approx([20,20])

def test_database_version_refusal_is_read_only(tmp_path):
    path=tmp_path/"old.sqlite"
    with sqlite3.connect(path) as conn: conn.execute("CREATE TABLE old_data (value)")
    before=path.read_bytes()
    with pytest.raises(ValueError,match="旧版"): Store(path)
    assert path.read_bytes()==before

def test_second_executor_cannot_acquire_same_database(factory,tmp_path):
    e,_,_=factory()
    other=Store(tmp_path/"a.sqlite")
    try:
        with pytest.raises(RuntimeError): other.acquire()
    finally: other.close()


def test_recorded_decision_replay_is_read_only_and_checks_full_result(factory,tmp_path,monkeypatch):
    from executor import runner
    from executor.replay_check import replay_day
    monkeypatch.setitem(runner.STRATEGY_TYPES,"passive",lambda **kw:Passive())
    e,_,st=factory(prime=False)
    t=T-timedelta(seconds=30)
    e.on_quotes(t,[q(A,t),q(B,t)])
    e.on_timer(T+timedelta(seconds=3))
    before=st.path.read_bytes()
    cfg={"engine":{},"strategy":[{"name":"r","type":"passive","capital":1000}]}
    report=replay_day(cfg,st.path,None,T.date())
    assert report["决策层_时点数"]==1 and report["决策层_不一致"]==0
    assert st.path.read_bytes()==before
    original=Passive.on_snapshot
    def changed(self,ctx,snap):
        original(self,ctx,snap); self.last_decision["action"]="changed"
    monkeypatch.setattr(Passive,"on_snapshot",changed)
    assert replay_day(cfg,st.path,None,T.date())["决策层_不一致"]==1


def test_report_uses_unit_pnl_series_instead_of_account_equity(tmp_path):
    import pandas as pd
    from executor.data import write_quotes
    from executor.report import summarize
    store=Store(tmp_path/"report.sqlite")
    times=pd.date_range("2026-01-05",periods=3)
    for i,t in enumerate(times):
        book={"strategy":"r","capital":1000,"cash":999,"positions":{A:1}}
        store.end_of_day(t.date(),"r",book,{},1000+i)
        store.conn.execute("INSERT INTO unit_returns VALUES (?,?,?,?)",(t.date().isoformat(),"r",0 if i==0 else 10,10*i))
    store.commit(); store.close()
    frame=pd.DataFrame({"last":[100,110,121],"bid1":[100,110,121],"ask1":[100,110,121],"iopv":[100,110,121]},index=times)
    write_quotes(tmp_path/"prices",A,"data",frame)
    report=summarize(tmp_path/"report.sqlite",tmp_path/"prices",[{"name":"r","symbols":[A]}],times[0].to_pydatetime(),datetime(2026,1,8))
    assert report["return_basis"]=="unit_position"
    assert report["summary"]["r"]["年化收益%"]==2520


def test_warmup_uses_strategy_interface_without_trading(factory):
    class Buying(Passive):
        def on_snapshot(self,ctx,snap):
            self.last_decision={"action":"buy"}
            return TargetIntent("r",str(snap.time),snap.time,{A:1})
    e,b,st=factory(strategy=Buying(),prime=False)
    t=T
    e.warmup([("quotes",t,[Quote(A,t,1,.999,1.001,1,True),Quote(B,t,1,.999,1.001,1,True)])])
    assert not b.sent and not e.oms.orders
    assert st.decisions_on(T.date())[0][2]["decision"]["action"]=="buy"


def test_existing_run_is_not_deleted(tmp_path):
    from executor.runner import run_backtest
    existing=tmp_path/"run"; existing.mkdir(); db=existing/"executor.sqlite"; db.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        run_backtest({"engine":{},"strategy":[]},T,T+timedelta(days=1),tmp_path/"none",existing)
    assert db.read_bytes()==b"keep"


def test_final_samples_wait_for_all_subscribed_symbols(factory):
    e,_,st=factory(prime=False)
    e.on_quotes(T,[Quote(A,T,1,.999,1.001,1,True)])
    assert not st.decisions_on(T.date())
    e.on_quotes(T,[Quote(B,T,1,.999,1.001,1,True)])
    rows=st.decisions_on(T.date())
    assert len(rows)==1 and rows[0][2]["stale"]==[]


def test_interrupted_warmup_stays_paused_after_restart(factory,tmp_path):
    e,b,st=factory(prime=False)
    def broken():
        yield "quotes",T,[Quote(A,T,1,.999,1.001,1,True),Quote(B,T,1,.999,1.001,1,True)]
        raise OSError("history incomplete")
    with pytest.raises(OSError): e.warmup(broken())
    st.close()
    restored=Store(tmp_path/"a.sqlite")
    e2=Engine(clock=SimClock(T),market_gw=ReplayMarket(),trade_gw=b,strategies=[Passive()],capitals={"r":1000},store=restored,risk=RiskManager(RiskConfig()))
    try:
        assert e2.start() and not e2.trading_enabled
    finally: restored.close()


class Counting(Passive):
    """带累积状态的策略：用于验证跨日回放从前一日收盘状态顺推。"""
    def __init__(self):
        super().__init__(); self.n=0
    def on_snapshot(self,ctx,snap):
        self.n+=1; self.last_decision={"action":"hold","n":self.n}
    def state(self): return {"n":self.n}
    def restore(self,state): self.n=state.get("n",0)


def test_decisions_store_hashes_and_replay_chains_from_previous_close(factory,monkeypatch):
    from executor import runner
    from executor.replay_check import replay_day
    monkeypatch.setitem(runner.STRATEGY_TYPES,"counting",lambda **kw:Counting())
    e,_,st=factory(strategy=Counting(),prime=False)
    day2=T+timedelta(days=1)
    for t in (T,T+timedelta(minutes=5),day2):
        e.on_quotes(t,[Quote(A,t,1,.999,1.001,1,True),Quote(B,t,1,.999,1.001,1,True)])
    payload=st.decisions_on(day2.date())[0][2]
    assert "state_before" not in payload and len(payload["state_before_hash"])==64
    cfg={"engine":{},"strategy":[{"name":"r","type":"counting","capital":1000}]}
    report=replay_day(cfg,st.path,None,day2.date())
    assert report["决策层_时点数"]==1 and report["决策层_不一致"]==0


def test_strategy_decides_without_waiting_for_other_strategies_symbols(tmp_path):
    C="513003.SH"
    class Own(Passive):
        name="own"; symbols=[A,B]
    class Other(Passive):
        name="other"; symbols=[C]
    store=Store(tmp_path/"m.sqlite")
    e=Engine(clock=SimClock(T-timedelta(minutes=1)),market_gw=ReplayMarket(),trade_gw=ControlledBroker(),
             strategies=[Own(),Other()],capitals={"own":1000,"other":1000},store=store,risk=RiskManager(RiskConfig()))
    try:
        assert e.start()==[]
        e.on_quotes(T,[Quote(A,T,1,.999,1.001,1,True),Quote(B,T,1,.999,1.001,1,True)])
        assert [(r[1],r[0]) for r in store.decisions_on(T.date())]==[("own",T.isoformat())]
        later=T+timedelta(minutes=1)
        e.on_quotes(later,[Quote(A,later,1,.999,1.001,1,True),Quote(B,later,1,.999,1.001,1,True)])
        other=[r for r in store.decisions_on(T.date()) if r[1]=="other"]
        assert len(other)==1 and other[0][2]["stale"]==[C]
    finally: store.close()


class SilentCancelBroker(ControlledBroker):
    def __init__(self):
        super().__init__(); self.cancels=0
    def cancel_order(self,o):
        self.cancels+=1  # 撤单请求发出但永远没有回报


def test_lost_cancel_reply_is_polled_and_resent(factory):
    from executor.engine import POLL_SECONDS
    b=SilentCancelBroker(); e,_,st=factory(broker=b)
    target(e); e.settle(T)
    o=e.oms.active()[0]; e.cancel(o)
    assert o.status is OrderStatus.CANCELLING and b.cancels==1
    e.clock.set(T+timedelta(seconds=POLL_SECONDS+1)); e.poll_broker(e.clock.now())
    assert b.cancels==2 and o.status is OrderStatus.CANCELLING and e.trading_enabled


def test_order_missing_at_broker_becomes_unknown_and_halts(factory):
    from executor.engine import POLL_SECONDS
    b=SilentCancelBroker(); e,_,st=factory(broker=b)
    target(e); e.settle(T)
    o=e.oms.active()[0]; e.cancel(o); b.updates.clear()
    e.clock.set(T+timedelta(seconds=POLL_SECONDS+1)); e.poll_broker(e.clock.now())
    assert o.status is OrderStatus.UNKNOWN and not e.trading_enabled and o.reserved==o.volume


def test_paper_mode_never_logs_into_account(tmp_path,monkeypatch):
    from executor import runner
    from executor.gateways import qmt
    created=[]; seen={}
    class FakeMarket:
        def __init__(self): self.sink=lambda e:None
        def subscribe(self,symbols): pass
        def close(self): pass
    class ForbiddenAccount:
        def __init__(self,*args,**kwargs): created.append(args)
    def finish_immediately(self,stop_check,**kwargs):
        seen["trade"]=type(self.trade_gw).__name__; self.finish()
    monkeypatch.setattr(qmt,"QmtMarketGateway",FakeMarket)
    monkeypatch.setattr(qmt,"QmtTradeGateway",ForbiddenAccount)
    monkeypatch.setattr(Engine,"run_live",finish_immediately)
    cfg={"engine":{"runtime_dir":str(tmp_path/"rt"),"recording_dir":str(tmp_path/"rec")},"risk":{"stop_file":str(tmp_path/"STOP")},
         "strategy":[{"name":"r","type":"same_index_rotation","symbols":[A,B],"threshold":0.3,"capital":1000}]}
    runner.run_realtime(cfg,"paper")
    assert not created and seen["trade"]=="SimBroker"


def test_late_older_quote_cannot_trigger_sim_fill():
    from executor.events import Order
    clock=SimClock(T); b=SimBroker(clock,10000); events=[]; b.sink=events.append
    b.on_quotes(T,[Quote(A,T,1,.999,1.001,1)])
    b.send_order(Order("c|1","r","i",A,Side.BUY,1.0,100,T,updated=T))
    now=T+timedelta(seconds=2); clock.set(now)
    b.on_quotes(now,[Quote(A,now,1,.999,1.001,1)])
    late=T+timedelta(seconds=5); clock.set(late)
    b.on_quotes(late,[Quote(A,T+timedelta(seconds=1),.999,.998,.999,1)])  # 迟到的旧报价：卖一 .999 本可成交
    assert not any(isinstance(e,Trade) for e in events) and b.quotes[A].time==now


def test_update_package_includes_executor_but_not_local_config(tmp_path,monkeypatch):
    import zipfile
    from scripts import package_update
    for name in ("backend/a.py","executor/engine.py","executor/config.toml","frontend/dist/index.html","start-executor.bat"):
        path=tmp_path/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text("x",encoding="utf-8")
    monkeypatch.setattr(package_update,"ROOT",tmp_path)
    package_update.main()
    names=zipfile.ZipFile(next((tmp_path/"outputs").glob("*.zip"))).namelist()
    assert "gyro_nicert/executor/engine.py" in names and "gyro_nicert/start-executor.bat" in names
    assert "gyro_nicert/executor/config.toml" not in names


def test_status_text_shows_quotes_trading_state_and_warmup(factory):
    from executor.strategies.same_index_rotation import SameIndexRotation
    e,_,_=factory(strategy=SameIndexRotation("r",[A,B],0.3))
    text=e.status_text(T)
    assert "行情 2/2 只在更新（含 IOPV 2）" in text and "交易启用" in text and "预热中 0.0/10 天" in text
    e._halt(T,"测试暂停")
    assert "已暂停：测试暂停" in e.status_text(T)