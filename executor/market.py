"""报价缓存及按分钟结束的多标的快照；封口后迟到报价不改写已决策输入。"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timedelta
from .events import Quote, Snapshot

class MarketCache:
    def __init__(self,max_age_seconds=90.0):
        self.max_age=timedelta(seconds=max_age_seconds)
        self.latest={}
        self.pending={}
        self.closed_through=None

    def update(self,quote):
        old=self.latest.get(quote.symbol)
        if old is not None and quote.time < old.time:
            return False
        self.latest[quote.symbol]=quote
        end=quote.time if quote.interval_end else quote.time.replace(second=0,microsecond=0)+timedelta(minutes=1)
        if self.closed_through is None or end > self.closed_through:
            bucket=self.pending.setdefault(end,{})
            previous=bucket.get(quote.symbol)
            if previous is None or quote.time >= previous.time:
                bucket[quote.symbol]=quote
        return True

    def snapshot(self,symbols,t,quotes=None,require_iopv=True):
        source=self.latest if quotes is None else quotes
        rows={s:source[s] for s in symbols if s in source}
        stale={s for s in symbols if s not in rows or not rows[s].valid or (require_iopv and rows[s].premium is None)
               or not timedelta(0) <= t-rows[s].time <= self.max_age}
        return Snapshot(t,rows,stale)

    def ready(self,cutoff):
        result=[]
        for end in sorted(self.pending):
            if end <= cutoff:
                result.append((end,self.pending[end]))
        for end,_ in result:
            del self.pending[end]
        self.closed_through=max(cutoff,self.closed_through) if self.closed_through else cutoff
        return result

    def mid(self,symbol):
        q=self.latest.get(symbol)
        return q.mid if q is not None and q.valid else None

    def fresh(self,symbol,now):
        q=self.latest.get(symbol)
        return q is not None and q.valid and timedelta(0) <= now-q.time <= self.max_age

    def state(self):
        return {"latest":[asdict(q) for q in self.latest.values()], "pending":{t.isoformat():[asdict(q) for q in qs.values()] for t,qs in self.pending.items()},
                "closed_through":self.closed_through.isoformat() if self.closed_through else None}

    def restore(self,state):
        def quote(x):
            x=dict(x); x["time"]=datetime.fromisoformat(x["time"]); return Quote(**x)
        self.latest={q.symbol:q for q in map(quote,state.get("latest",[]))}
        self.pending={datetime.fromisoformat(t):{q.symbol:q for q in map(quote,rows)} for t,rows in state.get("pending",{}).items()}
        self.closed_through=datetime.fromisoformat(state["closed_through"]) if state.get("closed_through") else None
