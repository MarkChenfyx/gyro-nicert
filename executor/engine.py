"""单线程状态机：先持久化发送意图，成交去重入账，按封口窗口分发策略输入。"""
from __future__ import annotations
import hashlib
import json
import queue
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from math import isfinite
from .bars import BarGenerator
from .clock import DecisionScheduler, in_session
from .events import CancelError, CorporateAction, GatewayStatus, OrderStatus, OrderUpdate, Quote, Side, TargetIntent, Trade
from .execution import Executor
from .gateways.sim import SimBroker
from .market import MarketCache
from .oms import OrderManager
from .portfolio import Book, Ledger, UnitPerformance
from .strategies.base import Context

POLL_SECONDS=30

def state_digest(state):
    text=json.dumps(state,default=str,sort_keys=True,allow_nan=False,separators=(",",":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

class Engine:
    def __init__(self, *, clock, market_gw, trade_gw, strategies, capitals, store, risk, tplus1=None,
                 commission_bp=1.0, max_quote_age=90.0, actions=None, action_source=None, recorder=None, state_save_every=0,
                 snapshot_wait_seconds=2.0):
        if len({s.name for s in strategies}) != len(strategies) or set(capitals) != {s.name for s in strategies}:
            raise ValueError("策略名称必须唯一，且与资金分配一致")
        if any(not isfinite(c) or c <= 0 for c in capitals.values()) or commission_bp < 0 or snapshot_wait_seconds < 0:
            raise ValueError("资金、手续费或等待时间非法")
        self.clock,self.market_gw,self.trade_gw=clock,market_gw,trade_gw
        self.strategies={s.name:s for s in strategies}
        self.capitals,self.store,self.risk=capitals,store,risk
        self.tplus1=set(tplus1 or ())
        self.commission_bp=commission_bp
        self.market=MarketCache(max_quote_age)
        self.bars=BarGenerator()
        self.subscriptions={s.name:s.subscription() for s in strategies}
        for sub in self.subscriptions.values():
            for symbol in sub.symbols:
                self.bars.subscribe(symbol,sub.bar_minutes)
        self.ledger=Ledger()
        self.performance=UnitPerformance()
        self.oms=OrderManager()
        self.executor=Executor(self)
        self.recorder=recorder
        self.schedulers={s.name:DecisionScheduler(s.step_minutes) for s in strategies}
        self.actions={}
        for a in actions or ():
            self.actions.setdefault(a.date.date(),[]).append(a)
        self.wait=timedelta(seconds=snapshot_wait_seconds)
        self.trading_enabled=False
        self.halt_reason=""
        self._day=None
        self._last_time=None
        self._events=queue.Queue()
        self._quotes=queue.Queue()
        self._started=False
        self._warming=False
        self._dirty=set(self.strategies)
        self._last_poll=None
        self.action_source=action_source  # 可选：day → 当日除权除息列表（实盘从 QMT 读取）
        self._prev_last={}
        self._day_ratio={}
        market_gw.sink=self.post
        trade_gw.sink=self.post

    def post(self,event):
        (self._quotes if isinstance(event,tuple) else self._events).put(event)

    def checkpoint(self):
        now=self.clock.now()
        for name in self.strategies:
            self.store.save_book(now,self.ledger.books[name].to_dict())
        for name in self._dirty:  # 策略状态只在决策或回报后变化，未变化时不重复序列化
            self.store.save_state(now,name,self.strategies[name].state())
        self._dirty.clear()
        self.store.save_runtime("engine",{"day":self._day,"last_time":self._last_time,
            "warming":self._warming,
            "configuration":{n:s.configuration() for n,s in self.strategies.items()},
            "market":self.market.state(),"bars":self.bars.state(),"executor":self.executor.state(),
            "risk":self.risk.state(),"prefix":self.oms.prefix,"schedulers":{n:s.state() for n,s in self.schedulers.items()},
            "performance":self.performance.state(),"broker":self.trade_gw.state() if isinstance(self.trade_gw,SimBroker) else None})
        self.store.commit()

    def start(self):
        self.store.acquire()
        try:
            books={b["strategy"]:b for b in self.store.load_books()}
            if set(books)-set(self.strategies):
                raise ValueError("交易库策略与配置不一致，请使用新的运行目录")
            states=self.store.load_states()
            for name,cap in self.capitals.items():
                self.ledger.books[name]=Book.from_dict(books[name]) if name in books else Book(name,cap,cap)
                if self.ledger.books[name].capital != cap:
                    raise ValueError("已有账本的资金分配不能直接更改")
                self.strategies[name].restore(states.get(name,{}))
            state=self.store.load_runtime("engine")
            if state and state.get("configuration") != {n:s.configuration() for n,s in self.strategies.items()}:
                raise ValueError("策略定义或参数已变化，请使用新的运行目录")
            self.oms.restore(self.store.load_orders(),self.store.trade_ids(),self.store.accounted())
            if state:
                self._day=date.fromisoformat(state["day"]) if state.get("day") else None
                self._last_time=datetime.fromisoformat(state["last_time"]) if state.get("last_time") else None
                if hasattr(self.clock,"set") and self._last_time and self._last_time > self.clock.now():
                    self.clock.set(self._last_time)
                self.oms.prefix=state["prefix"]
                self.market.restore(state["market"])
                self.bars.restore(state["bars"])
                self.executor.restore(state["executor"])
                self.risk.restore(state["risk"])
                self.performance.restore(state["performance"])
                for n,s in state["schedulers"].items():
                    self.schedulers[n].restore(s)
                if isinstance(self.trade_gw,SimBroker) and state.get("broker"):
                    self.trade_gw.restore(state["broker"])
            for name in self.strategies:
                self.performance.open(name)
            self.trade_gw.restore_orders(list(self.oms.orders.values()))
            self._started=True
            if not hasattr(self.clock,"set") and self._day and self._day != self.clock.now().date():
                self.advance(self.clock.now())
                self._new_day(self.clock.now())
            problems=self.reconcile()
            if state.get("warming"):
                problems.append("上次历史预热未完成，请核查数据并使用新的运行目录")
            self.trading_enabled=not problems
            self.halt_reason="；".join(problems)
            self.market_gw.subscribe(sorted({s for sub in self.subscriptions.values() for s in sub.symbols}))
            self.store.event(self.clock.now(),"start",trading_enabled=self.trading_enabled,problems=problems)
            self.checkpoint()
            return problems
        except BaseException:
            self.store.release()
            raise

    def reconcile(self):
        problems=[]
        try:
            for trade in self.trade_gw.query_trades():
                self.on_trade(trade)
            updates=self.trade_gw.query_order_updates()
            known={u.client_id for u in updates}
            for update in updates:
                self.on_order_update(update)
            for o in self.oms.active():
                if o.client_id not in known or o.accounted < o.filled:
                    o.status=OrderStatus.UNKNOWN
                    self.store.order(o)
                    problems.append(f"委托 {o.client_id} 尚未完成成交核对")
            broker=self.trade_gw.query_positions()
            own={s:q for s,q in self.ledger.total_positions().items() if q}
            if broker != own:
                problems.append("账户持仓与本引擎账本不一致；共用账户必须先完成统一归属协调")
            cash=self.trade_gw.query_cash()
            if not isfinite(cash) or cash < 0:
                problems.append("账户可用资金查询无效")
        except Exception as exc:
            problems.append(f"账户核对失败：{exc}")
        if self.halt_reason:
            problems.append(self.halt_reason)
        return problems

    def _halt(self,now,message):
        self.trading_enabled=False
        self.halt_reason=message
        self.store.event(now,"gateway_down",message=message)

    def can_trade(self,name,now):
        return not self._warming and self.trading_enabled and in_session(now) and not self.risk.stopped() and not self.risk.halted(name)

    def warmup(self,events):
        """用同一行情/Bar接口预热空账户策略，预热期间禁止报单。"""
        if self.oms.orders or any(b.positions for b in self.ledger.books.values()):
            raise ValueError("已有交易状态应直接恢复，不能重新预热")
        from .clock import SimClock
        clock,recorder=self.clock,self.recorder
        self.clock=SimClock()
        if isinstance(self.trade_gw,SimBroker):
            self.trade_gw.clock=self.clock
        self.recorder=None
        self._warming=True
        completed=False
        try:
            for kind,t,quotes in events:
                if not hasattr(clock,"set") and t >= clock.now():
                    raise ValueError("预热数据必须早于实盘时间")
                if kind=="quotes": self.on_quotes(t,quotes)
                else: self.on_timer(t)
            completed=True
        finally:
            if hasattr(clock,"set") and self._last_time and self._last_time > clock.now():
                clock.set(self._last_time)
            self.clock,self.recorder=clock,recorder
            if isinstance(self.trade_gw,SimBroker): self.trade_gw.clock=clock
            self._warming=not completed
            self.checkpoint()

    def available_cash(self,name):
        rate=1+self.commission_bp/1e4
        orders=[o for o in self.oms.active() if o.side is Side.BUY]
        own=sum(o.price*o.reserved*rate for o in orders if o.strategy==name)
        total=sum(o.price*o.reserved*rate for o in orders)
        try:
            cash=self.trade_gw.query_cash()
            if not isfinite(cash) or cash < 0:
                raise ValueError("账户可用资金无效")
            return max(0.0,min(self.ledger.books[name].cash-own,cash-total))
        except Exception as exc:
            self._halt(self.clock.now(),f"查询可用资金失败：{exc}")
            return 0.0

    def available_sellable(self,name,symbol):
        orders=[o for o in self.oms.active() if o.side is Side.SELL and o.symbol==symbol]
        own=sum(o.reserved for o in orders if o.strategy==name)
        total=sum(o.reserved for o in orders)
        try:
            qty=self.trade_gw.query_sellable_positions().get(symbol,0)
            return max(0,min(self.ledger.books[name].sellable(symbol,symbol in self.tplus1)-own,qty-total))
        except Exception as exc:
            self._halt(self.clock.now(),f"查询可卖数量失败：{exc}")
            return 0

    def on_quotes(self,t,quotes):
        if hasattr(self.clock,"set"):
            self.clock.set(t)
        self._last_time=t
        quotes=[replace(q,iopv=None) if q.iopv is not None and not isfinite(q.iopv) else q
                for q in quotes if q.valid and q.time <= t]
        self.drain()
        if self._day != t.date():
            self.advance(t)
            self._new_day(t)
        if self.recorder:
            self.recorder.add(quotes,t)
        for q in quotes:
            if q.time > t or not q.valid:
                continue
            if q.previous_close is not None and isfinite(q.previous_close) and q.previous_close > 0 and q.symbol in self._prev_last:
                self._check_reference(t,q.symbol,self._prev_last.pop(q.symbol),q.previous_close)
            if self.market.update(q):
                if q.previous_close is not None and isfinite(q.previous_close) and q.previous_close > 0:
                    self.performance.references[q.symbol]=q.previous_close
                self.performance.mark(q.symbol,q.mid)
                self.bars.update(q,self.market.closed_through)
        if isinstance(self.trade_gw,SimBroker):
            self.trade_gw.on_quotes(t,quotes)
        self.drain()
        self.advance(t)  # 先按等待时间释放更早的窗口，保证决策按时间顺序
        if quotes and all(q.interval_end for q in quotes):
            # 分钟采样：某策略自己的标的在本窗口都已到齐就立即决策，不等其他策略缺失或未上市的标的。
            bucket=self.market.pending.get(t,{})
            for name,sub in self.subscriptions.items():
                if sub.snapshots and set(sub.symbols) <= bucket.keys() and self.schedulers[name].due(t):
                    self.decide(t,[name],bucket,t)
            required={s for sub in self.subscriptions.values() for s in sub.symbols}
            if required <= bucket.keys():
                self.advance(t,closed=t)
        for name,sub in self.subscriptions.items():
            if sub.ticks:
                for q in quotes:
                    if q.symbol in sub.symbols and self.market.latest.get(q.symbol)==q and self.market.fresh(q.symbol,t):
                        self._decision(name,"on_tick",t,t,(q,),{"kind":"tick","quote":asdict(q)})
        self.settle(t)
        self.checkpoint()

    def on_timer(self,t):
        if hasattr(self.clock,"set"):
            self.clock.set(t)
        self._last_time=t
        if self.recorder:
            self.recorder.event("timer",t)
        self.drain()
        self.advance(t)
        self.settle(t)
        self.checkpoint()

    def advance(self,now,closed=None):
        cutoff=closed if closed is not None else now-self.wait
        for end,quotes in self.market.ready(cutoff):
            due=[n for n,sch in self.schedulers.items() if self.subscriptions[n].snapshots and sch.due(end)]
            self.decide(end,due,quotes,now)
        bars=self.bars.advance(cutoff)
        groups={}
        for b in bars:
            groups.setdefault((b.end,b.minutes),{})[b.symbol]=b
        for (end,minutes),rows in sorted(groups.items()):
            for name,sub in self.subscriptions.items():
                if minutes in sub.bar_minutes:
                    selected={s:b for s,b in rows.items() if s in sub.symbols}
                    missing={s for s in sub.symbols if s not in selected or not selected[s].complete}
                    self._decision(name,"on_bars",end,now,(end,minutes,selected,missing),
                        {"kind":"bars","end":end,"minutes":minutes,"bars":[asdict(b) for b in selected.values()],"missing":sorted(missing)})

    def drain(self):
        n=0
        while True:
            try: ev=self._events.get_nowait()
            except queue.Empty: return n
            n+=1
            if isinstance(ev,OrderUpdate): self.on_order_update(ev)
            elif isinstance(ev,Trade): self.on_trade(ev)
            elif isinstance(ev,GatewayStatus) and not ev.connected: self._halt(ev.time,ev.message)
            elif isinstance(ev,CancelError):
                o=self.oms.orders.get(ev.client_id)
                if o is None:
                    self._halt(ev.time,"撤单错误无法关联到本地委托："+ev.message)
                elif o.status.active:
                    o.status=OrderStatus.UNKNOWN
                    o.reason=ev.message
                    self.store.order(o)
                    self._halt(ev.time,"撤单结果不确定："+ev.message)
        return n

    def poll_broker(self,now):
        """定时查询结果未确认的委托（待确认、撤单中、状态不明），补记丢失的回报；不重发委托，查不到就暂停待人工核对。"""
        uncertain=[o for o in self.oms.active() if o.status in (OrderStatus.PENDING,OrderStatus.CANCELLING,OrderStatus.UNKNOWN)
                   and (now-(o.updated or o.created)).total_seconds() >= POLL_SECONDS]
        if not uncertain or (self._last_poll and (now-self._last_poll).total_seconds() < POLL_SECONDS):
            return
        self._last_poll=now
        try:
            trades=self.trade_gw.query_trades()
            updates=self.trade_gw.query_order_updates()
        except Exception as exc:
            self.store.event(now,"broker_query_failed",message=str(exc))
            return
        for trade in trades:
            self.on_trade(trade)
        reported={}
        for update in updates:
            self.on_order_update(update)
            reported[update.client_id]=update
        for o in uncertain:
            u=reported.get(o.client_id)
            if u is None:
                if o.status is not OrderStatus.UNKNOWN:  # 已是未知状态的委托此前已暂停交易，不重复告警
                    o.status=OrderStatus.UNKNOWN
                    self.store.order(o)
                    self._halt(now,f"券商查询不到委托 {o.client_id}，需人工核对")
            elif o.status is OrderStatus.CANCELLING and u.status in (OrderStatus.SUBMITTED,OrderStatus.PARTIAL):
                self.cancel(o)  # 撤单请求或其回报丢失，券商仍显示有效：重发撤单，资源继续冻结
        self.checkpoint()

    def settle(self,t):
        self.drain()
        self.poll_broker(t)
        self.executor.step(t)
        if isinstance(self.trade_gw,SimBroker):
            self.trade_gw.match(t)
        self.drain()

    def _ctx(self,name,now):
        return Context(now,deepcopy(self.ledger.books[name]),self.executor.active(name))

    def _invoke(self,name,method,*args):
        try: return getattr(self.strategies[name],method)(*args)
        except Exception as exc:
            self._halt(self.clock.now(),f"策略 {name} 的 {method} 异常：{exc}")
            return None

    def on_order_update(self,u):
        try: o=self.oms.apply_update(u)
        except ValueError as exc:
            self._halt(u.time,str(exc)); return
        if o is None: return
        self.store.order(o)
        if o.status is OrderStatus.REJECTED:
            self.store.event(u.time,"order_rejected",o.strategy,client_id=o.client_id,reason=o.reason)
        self._invoke(o.strategy,"on_order",self._ctx(o.strategy,u.time),deepcopy(o))
        self._dirty.add(o.strategy)
        self.checkpoint()

    def on_trade(self,t):
        if t.trade_id in self.oms._seen_trades:
            return
        original=self.oms.orders.get(t.client_id)
        if original and t.side is Side.SELL and t.volume > self.ledger.books[original.strategy].qty(t.symbol):
            self._halt(t.time,"成交卖出数量超过账本，需人工核对"); return
        try: o=self.oms.accept_trade(t)
        except ValueError as exc:
            self._halt(t.time,str(exc)); return
        if o is None:
            if t.trade_id not in self.oms._seen_trades:
                self._halt(t.time,"收到未知委托成交："+t.client_id)
            return
        before=self.ledger.books[o.strategy].qty(t.symbol)
        self.ledger.apply_trade(o.strategy,t)
        run=self.executor.runs.get(o.strategy)
        qty=run.quantities.get(t.symbol,0) if run and run.intent.intent_id==o.intent_id else 0
        weight=run.intent.targets.get(t.symbol,0) if run and run.intent.intent_id==o.intent_id else 0
        self.performance.trade(o.strategy,t,before,qty,weight)
        self.store.trade(o.strategy,t)
        self.store.order(o)
        self._invoke(o.strategy,"on_trade",self._ctx(o.strategy,t.time),t)
        self._dirty.add(o.strategy)
        self.checkpoint()

    def decide(self,t,names,quotes=None,now=None):
        now=now or t
        for name in names:
            sub=self.subscriptions[name]
            snap=self.market.snapshot(list(sub.symbols),t,quotes,require_iopv=sub.require_iopv)
            self._decision(name,"on_snapshot",t,now,(snap,),{"kind":"snapshot","stale":sorted(snap.stale),
                "snapshot":{"time":snap.time,"quotes":[asdict(q) for q in snap.quotes.values()],"stale":sorted(snap.stale)}})

    def _decision(self,name,method,event_time,now,args,payload):
        st=self.strategies[name]
        ctx=self._ctx(name,now)
        context_before={"now":now,"book":ctx.book.to_dict(),"intent_active":ctx.intent_active}
        before=state_digest(st.state())
        intent=self._invoke(name,method,ctx,*args)
        if intent is not None and (not isinstance(intent,TargetIntent) or intent.strategy != name):
            self._halt(now,"策略输出了非法或不属于自身的交易意图")
            intent=None
        self._dirty.add(name)
        # 完整状态只在每日收盘写入 state_history；逐次决策只记校验值，回放时从前一日状态顺推核对。
        self.store.decision(event_time,name,{**st.last_decision,**payload,"decision":deepcopy(st.last_decision),
            "intent":asdict(intent) if intent else None,
            "context":context_before,
            "state_before_hash":before,"state_after_hash":state_digest(st.state())})
        self.risk.check_equity(name,self._equity(self.ledger.books[name]))
        self._output(intent,now)

    def _output(self,intent,now):
        if intent is not None:
            self._submit(intent,now)

    def _submit(self,intent,t):
        name=intent.strategy
        reason=None
        if name not in self.strategies:
            reason="未知策略"
        elif not self.can_trade(name,t):
            reason=self.halt_reason or self.risk.halted(name) or "交易未启用或不在交易时段"
        elif (intent.created > t or intent.ttl_seconds <= 0 or not isfinite(intent.ttl_seconds)
              or t >= intent.created+timedelta(seconds=intent.ttl_seconds)):
            reason="交易意图已过期或时间非法"
        elif (not isinstance(intent.max_slip_ticks,int) or intent.max_slip_ticks < 0
              or not set(intent.targets) <= set(self.subscriptions[name].symbols)
              or any(not isfinite(w) or w < 0 for w in intent.targets.values()) or sum(intent.targets.values()) > 1+1e-9):
            reason="目标权重或执行参数非法"
        elif self.executor.active(name) or (name,intent.intent_id) in self.executor.seen:
            reason="已有未完成调仓或重复目标"
        elif any(not self.market.fresh(s,t) for s in set(intent.targets)|set(self.ledger.books[name].positions)):
            reason="目标或现有持仓行情缺失/过期"
        else:
            reason=self.risk.allow_intent(name)
        if reason:
            self.store.event(t,"intent_blocked",name,reason=reason)
            return False
        accepted=self.executor.submit(intent,t)
        self.checkpoint()
        return accepted

    def place(self,intent,symbol,side,price,volume,now):
        self.risk.check_equity(intent.strategy,self._equity(self.ledger.books[intent.strategy]))
        if not self.can_trade(intent.strategy,now) or not self.market.fresh(symbol,now):
            return False
        if side is Side.BUY and price*volume*(1+self.commission_bp/1e4) > self.available_cash(intent.strategy)+1e-8:
            return False
        if side is Side.SELL and volume > self.available_sellable(intent.strategy,symbol):
            return False
        if not self.can_trade(intent.strategy,now):
            return False
        o=self.oms.create(intent.strategy,intent.intent_id,symbol,side,price,volume,now)
        odd=side is Side.SELL and volume==self.ledger.books[intent.strategy].qty(symbol)
        reason=self.risk.check_order(o,self.market.mid(symbol),odd_lot_close=odd)
        if reason:
            o.status,o.reason=OrderStatus.REJECTED,reason
            self.store.order(o)
            self.store.event(now,"order_blocked",intent.strategy,client_id=o.client_id,reason=reason)
            self.checkpoint()
            return False
        self.store.order(o)
        self.checkpoint()  # 此提交必须在任何外部报单之前。
        try:
            self.trade_gw.send_order(o)
        except Exception as exc:
            o.status,o.reason=OrderStatus.UNKNOWN,str(exc)
            self.store.order(o)
            self._halt(now,"报单结果未知："+str(exc))
            self.checkpoint()
        return True

    def cancel(self,o):
        o.status=OrderStatus.CANCELLING
        self.store.order(o)
        self.checkpoint()
        try: self.trade_gw.cancel_order(o)
        except Exception as exc:
            self.post(CancelError(o.client_id,self.clock.now(),str(exc)))

    def _equity(self,book):
        return book.cash+sum(q*(self.market.mid(s) or self.performance.prices.get(s,0)) for s,q in book.positions.items())

    def _notify_action(self,t,symbol,ratio):
        for name,sub in self.subscriptions.items():
            if symbol in sub.symbols:
                self._invoke(name,"on_corporate_action",self._ctx(name,t),symbol,ratio)
                self._dirty.add(name)

    def _check_reference(self,t,symbol,last,reference):
        """前收盘参考价（交易所已按除权调整）应≈昨日收盘×当日除权比例；不符说明除权数据缺失或错误。"""
        used=self._day_ratio.get(symbol,1.0)
        expected=last*used
        if abs(reference/expected-1) <= max(0.002,1.5*0.001/expected):
            return
        self.store.event(t,"corporate_action_mismatch",symbol=symbol,last_close=last,reference=reference,used_ratio=round(used,6))
        self._notify_action(t,symbol,reference/expected)  # 以交易所参考价为准修正价格历史
        for name,sub in self.subscriptions.items():
            if symbol in sub.symbols:
                self.risk.halt(name,f"{symbol} 除权数据与交易所前收盘价不一致，今日暂停，需人工核对")

    def _new_day(self,t):
        if self._day is not None:
            self.end_of_day(self._day)
        self._day=t.date()
        self.ledger.new_day(self._day)
        self.performance.new_day()
        if self.action_source is not None:  # 实盘/纸面：每天从行情源取当日除权除息
            try:
                fetched=[a for a in self.action_source(self._day) if a.date.date()==self._day]
            except Exception as exc:
                fetched=[]
                self.store.event(t,"corporate_action_source_failed",message=str(exc))
            known={a.symbol for a in self.actions.get(self._day,[])}
            new=[a for a in fetched if a.symbol not in known]
            self.actions.setdefault(self._day,[]).extend(new)
            if new and isinstance(self.trade_gw,SimBroker):
                self.trade_gw.add_actions(new)
        # 昨日最后成交价：开盘后与交易所公布的前收盘参考价核对除权数据
        self._prev_last={s:q.last for s,q in self.market.latest.items() if q.valid and q.last > 0}
        self._day_ratio={}
        for a in self.actions.get(self._day,[]):
            prev=self._prev_last.get(a.symbol) or self.market.mid(a.symbol)
            if prev and a.split_ratio > 0 and prev > a.cash_per_share:
                self._day_ratio[a.symbol]=(prev-a.cash_per_share)/prev/a.split_ratio
                self._notify_action(t,a.symbol,self._day_ratio[a.symbol])
            self.ledger.apply_action(a)
            for name,b in self.performance.books.items():
                self.performance._add(name,a.symbol,b["units"].get(a.symbol,0)*a.cash_per_share)
            if a.split_ratio != 1 and a.symbol in self.performance.prices:
                self.performance.prices[a.symbol]/=a.split_ratio
                if a.symbol in self.performance.references:
                    self.performance.references[a.symbol]/=a.split_ratio
            self.store.event(t,"corporate_action",symbol=a.symbol,cash=a.cash_per_share,split=a.split_ratio)
        self.risk.new_day(self._day,{n:self._equity(b) for n,b in self.ledger.books.items()})

    def end_of_day(self,d):
        for name,st in self.strategies.items():
            b=self.ledger.books[name]
            self.store.end_of_day(d,name,b.to_dict(),st.state(),self._equity(b))
            p=self.performance.books[name]
            self.store.conn.execute("INSERT OR REPLACE INTO unit_returns VALUES (?,?,?,?)",
                (d.isoformat(),name,p["daily"] if p["valid"] else None,p["cumulative"] if p["complete"] else None))
        self.checkpoint()

    def finish(self):
        self.drain()
        self.advance(self.clock.now())
        if self._day is not None:
            self.end_of_day(self._day)
        self.checkpoint()
        self.store.release()

    def status_text(self,now):
        """给运行窗口看的一段状态：行情是否在进来、能否交易、在途委托、各策略持仓与预热进度。"""
        symbols=sorted({s for sub in self.subscriptions.values() for s in sub.symbols})
        fresh=[s for s in symbols if self.market.fresh(s,now)]
        iopv=sum(1 for s in fresh if self.market.latest[s].iopv is not None)
        if self.risk.stopped(): state="STOP 文件生效，拒绝新委托"
        elif self.trading_enabled: state="交易启用"
        else: state="已暂停："+self.halt_reason
        lines=[f"行情 {len(fresh)}/{len(symbols)} 只在更新（含 IOPV {iopv}）｜{'交易时段' if in_session(now) else '非交易时段'}｜{state}｜在途委托 {len(self.oms.active())}"]
        for name,st in self.strategies.items():
            hold="、".join(f"{s}×{q}" for s,q in self.ledger.books[name].positions.items() if q) or "空仓"
            extra=st.status()
            lines.append(f"  {name}: {hold}"+(f"｜{extra}" if extra else "")+("｜当日熔断" if self.risk.halted(name) else ""))
        return "\n".join(lines)

    def run_live(self,stop_check,heartbeat_seconds=1.0,console=None,status_seconds=60.0):
        last_status=None
        while not stop_check():
            try:
                _,_,quotes=self._quotes.get(timeout=heartbeat_seconds)
                self.on_quotes(self.clock.now(),quotes)
            except queue.Empty:
                pass
            now=self.clock.now()
            self.on_timer(now)
            if console and (last_status is None or (now-last_status).total_seconds() >= status_seconds):
                last_status=now
                console(self.status_text(now))
        self.finish()
