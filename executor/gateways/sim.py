"""按新报价事件撮合；同一订单对同一报价只消耗一次模拟流动性。"""
from __future__ import annotations
import random
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from ..events import CancelError, Order, OrderStatus, OrderUpdate, Quote, Side, Trade
from .base import MarketGateway, TradeGateway

@dataclass
class _Pending:
    order: Order
    eligible: datetime
    filled: int = 0
    amount: float = 0.0
    cancel_at: datetime | None = None
    version: int = 0

def _order(d):
    x=dict(d)
    x["side"],x["status"]=Side(x["side"]),OrderStatus(x["status"])
    x["created"]=datetime.fromisoformat(x["created"])
    x["updated"]=datetime.fromisoformat(x["updated"]) if x.get("updated") else None
    return Order(**x)

def _tuples(x):
    return tuple(_tuples(v) for v in x) if isinstance(x,list) else x

class SimBroker(TradeGateway):
    def __init__(self,clock,cash,latency_seconds=0.0,commission_bp=1.0,min_fee=0.0,fill_ratio=1.0,reject_rate=0.0,seed=0,tplus1=None,actions=None):
        if not 0 < fill_ratio <= 1 or not 0 <= reject_rate <= 1 or latency_seconds < 0:
            raise ValueError("模拟成交参数非法")
        self.clock,self.cash=clock,cash
        self.positions={}
        self.bought_today={}
        self.latency=timedelta(seconds=latency_seconds)
        self.commission_bp,self.min_fee=commission_bp,min_fee
        self.fill_ratio,self.reject_rate=fill_ratio,reject_rate
        self.rng=random.Random(seed)
        self.tplus1=set(tplus1 or ())
        self.quotes={}
        self.pending={}
        self.versions={}
        self._updates={}
        self._trades=[]
        self._trade_seq=0
        self._day=None
        self._actions={}
        for a in actions or ():
            self._actions.setdefault(a.date.date(),[]).append(a)
        self.sink=lambda event:None

    def add_actions(self,actions):
        """纸面模式：引擎每天从行情源取到的除权除息同步给模拟券商，须在该日首批报价前调用。"""
        for a in actions:
            self._actions.setdefault(a.date.date(),[]).append(a)

    def _update(self,u):
        self._updates[u.client_id]=u
        self.sink(u)

    def send_order(self,o):
        now=self.clock.now()
        if o.client_id in self._updates:
            raise ValueError("模拟网关拒绝重复客户端编号")
        if self.reject_rate and self.rng.random() < self.reject_rate:
            self._update(OrderUpdate(o.client_id,OrderStatus.REJECTED,0,0.0,now,reason="模拟随机拒单"))
            return
        self.pending[o.client_id]=_Pending(o,now+self.latency,version=self.versions.get(o.symbol,0))
        self._update(OrderUpdate(o.client_id,OrderStatus.SUBMITTED,0,0.0,now,broker_id="SIM"+o.client_id))

    def cancel_order(self,o):
        p=self.pending.get(o.client_id)
        if p is None:
            self.sink(CancelError(o.client_id,self.clock.now(),"模拟订单不存在，需查询确认"))
        elif p.cancel_at is None:
            p.cancel_at=self.clock.now()+self.latency

    def query_positions(self):
        return {s:q for s,q in self.positions.items() if q}

    def query_sellable_positions(self):
        return {s:max(0,q-(self.bought_today.get(s,0) if s in self.tplus1 else 0)) for s,q in self.positions.items() if q}

    def query_cash(self): return self.cash
    def query_trades(self): return list(self._trades)
    def query_order_updates(self): return list(self._updates.values())
    def query_open_orders(self):
        return {cid:{"status":u.status,"filled":u.filled,"avg_price":u.avg_price} for cid,u in self._updates.items() if cid in self.pending}

    def restore_orders(self,orders):
        by_id={o.client_id:o for o in orders}
        for cid,p in self.pending.items():
            if cid in by_id: p.order=by_id[cid]

    def on_quotes(self,t,quotes):
        if self._day != t.date():
            self._day=t.date()
            self.bought_today.clear()
            for a in self._actions.get(self._day,[]):
                q=self.positions.get(a.symbol,0)
                self.cash+=q*a.cash_per_share
                if q and a.split_ratio != 1:
                    self.positions[a.symbol]=int(round(q*a.split_ratio))
        for q in quotes:
            old=self.quotes.get(q.symbol)
            # 只接受更新的报价；同一时间戳仅在内容变化时算新行情。迟到的旧报价不得覆盖最新报价或触发撮合。
            if q.valid and q.time <= t and (old is None or q.time > old.time or (q.time == old.time and q != old)):
                self.quotes[q.symbol]=q
                self.versions[q.symbol]=self.versions.get(q.symbol,0)+1
        self.match(t)

    def match(self,t):
        for cid in list(self.pending):
            p=self.pending[cid]; o=p.order
            if p.cancel_at is not None and t >= p.cancel_at:
                self._finish(p,OrderStatus.CANCELLED,t); continue
            q=self.quotes.get(o.symbol)
            version=self.versions.get(o.symbol,0)
            if (q is None or not q.valid or t < p.eligible or q.time < p.eligible
                    or q.time > t or (t-q.time).total_seconds() > 90 or version <= p.version):
                continue
            p.version=version
            if o.side is Side.BUY and o.price >= q.ask: price=q.ask
            elif o.side is Side.SELL and o.price <= q.bid: price=q.bid
            else: continue
            remaining=o.volume-p.filled
            qty=remaining if self.fill_ratio==1 else min(remaining,max(100,int(remaining*self.fill_ratio)//100*100))
            fee=max(price*qty*self.commission_bp/1e4,self.min_fee)
            if o.side is Side.BUY:
                if self.cash < price*qty+fee:
                    self._finish(p,OrderStatus.REJECTED,t,"资金不足"); continue
                self.cash-=price*qty+fee
                self.positions[o.symbol]=self.positions.get(o.symbol,0)+qty
                self.bought_today[o.symbol]=self.bought_today.get(o.symbol,0)+qty
            else:
                if self.query_sellable_positions().get(o.symbol,0) < qty:
                    self._finish(p,OrderStatus.REJECTED,t,"可卖数量不足"); continue
                self.cash+=price*qty-fee
                self.positions[o.symbol]-=qty
            p.filled+=qty; p.amount+=price*qty; self._trade_seq+=1
            trade=Trade(f"SIMT{self._trade_seq}",cid,o.symbol,o.side,price,qty,t,fee)
            self._trades.append(trade); self.sink(trade)
            status=OrderStatus.FILLED if p.filled==o.volume else OrderStatus.PARTIAL
            self._update(OrderUpdate(cid,status,p.filled,p.amount/p.filled,t,broker_id="SIM"+cid))
            if status is OrderStatus.FILLED: del self.pending[cid]

    def _finish(self,p,status,t,reason=""):
        self._update(OrderUpdate(p.order.client_id,status,p.filled,p.amount/p.filled if p.filled else 0,t,reason=reason))
        del self.pending[p.order.client_id]

    def state(self):
        return {"cash":self.cash,"positions":self.positions,"bought_today":self.bought_today,"day":self._day,
            "versions":self.versions,"trade_seq":self._trade_seq,"quotes":[asdict(q) for q in self.quotes.values()],
            "updates":[asdict(u) for u in self._updates.values()],"trades":[asdict(t) for t in self._trades],"rng":self.rng.getstate(),
            "pending":{cid:{"order":p.order.to_dict(),"eligible":p.eligible,"filled":p.filled,"amount":p.amount,
                "cancel_at":p.cancel_at,"version":p.version} for cid,p in self.pending.items()}}

    def restore(self,state):
        self.cash=state["cash"]; self.positions=dict(state["positions"]); self.bought_today=dict(state["bought_today"])
        self._day=date.fromisoformat(state["day"]) if state.get("day") else None
        self.versions=dict(state["versions"]); self._trade_seq=state["trade_seq"]
        self.rng.setstate(_tuples(state["rng"]))
        self.quotes={}
        for d in state["quotes"]:
            x=dict(d); x["time"]=datetime.fromisoformat(x["time"]); q=Quote(**x); self.quotes[q.symbol]=q
        self._updates={}
        for d in state["updates"]:
            x=dict(d); x["time"]=datetime.fromisoformat(x["time"]); x["status"]=OrderStatus(x["status"])
            u=OrderUpdate(**x); self._updates[u.client_id]=u
        self._trades=[]
        for d in state["trades"]:
            x=dict(d); x["time"]=datetime.fromisoformat(x["time"]); x["side"]=Side(x["side"]); self._trades.append(Trade(**x))
        self.pending={}
        for cid,d in state["pending"].items():
            self.pending[cid]=_Pending(_order(d["order"]),datetime.fromisoformat(d["eligible"]),d["filled"],d["amount"],
                datetime.fromisoformat(d["cancel_at"]) if d["cancel_at"] else None,d["version"])

class ReplayMarket(MarketGateway):
    def __init__(self):
        self.sink=lambda event:None
        self.symbols=[]
    def subscribe(self,symbols): self.symbols=sorted(set(self.symbols)|set(symbols))
