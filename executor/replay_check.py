"""只读重放各次决策的实际输入，逐项核对输出与策略状态。

起点为前一交易日收盘的完整状态，之后按记录顺序顺推，每次决策前后用状态校验值核对；
真实成交会改变策略上下文，因此使用当时记录的真实上下文，不把模拟成交当成实盘事实。
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import tomllib
from dataclasses import asdict
from datetime import date,datetime
from pathlib import Path
from .engine import state_digest
from .events import Bar,Quote,Snapshot
from .portfolio import Book
from .runner import build_strategies,resolve
from .strategies.base import Context

def canonical(value):
    return json.loads(json.dumps(value,default=str,sort_keys=True,allow_nan=False))

def replay_day(cfg,live_db,data_dir,day):
    conn=sqlite3.connect(f"file:{Path(live_db).as_posix()}?mode=ro",uri=True)
    try:
        rows=conn.execute("SELECT time,strategy,payload FROM decisions WHERE substr(time,1,10)=? ORDER BY id",(day.isoformat(),)).fetchall()
        starts={r[0]:json.loads(r[1]) for r in conn.execute("SELECT strategy,state FROM state_history h WHERE day=(SELECT max(day) "
            "FROM state_history WHERE strategy=h.strategy AND day<?)",(day.isoformat(),))}
        strategies={s.name:s for s in build_strategies(cfg)}
        for name,state in starts.items():
            if name in strategies:
                strategies[name].restore(state)
        mismatches=[]; checked=0; broken=set()
        for time,name,text in rows:
            p=json.loads(text)
            if "context" not in p or "state_before_hash" not in p:
                return {"日期":str(day),"错误":"旧记录缺少实际决策输入，无法验证一致性"}
            if name in broken:
                continue
            st=strategies[name]
            if state_digest(st.state()) != p["state_before_hash"]:
                broken.add(name)
                mismatches.append({"时点":time,"策略":name,"错误":"起点状态与记录不一致（缺少前一日收盘状态，或决策之间状态被回报改变）"})
                continue
            ctx=Context(datetime.fromisoformat(p["context"]["now"]),Book.from_dict(p["context"]["book"]),p["context"]["intent_active"])
            kind=p.get("kind","snapshot")
            if kind=="snapshot":
                x=p["snapshot"]; quotes={}
                for d in x["quotes"]:
                    d=dict(d); d["time"]=datetime.fromisoformat(d["time"]); q=Quote(**d); quotes[q.symbol]=q
                intent=st.on_snapshot(ctx,Snapshot(datetime.fromisoformat(x["time"]),quotes,set(x["stale"])))
            elif kind=="tick":
                x=dict(p["quote"]); x["time"]=datetime.fromisoformat(x["time"])
                intent=st.on_tick(ctx,Quote(**x))
            else:
                bars={}
                for d in p["bars"]:
                    d=dict(d); d["start"],d["end"]=datetime.fromisoformat(d["start"]),datetime.fromisoformat(d["end"])
                    b=Bar(**d); bars[b.symbol]=b
                intent=st.on_bars(ctx,datetime.fromisoformat(p["end"]),p["minutes"],bars,set(p["missing"]))
            actual={"intent":canonical(asdict(intent)) if intent else None,"state_after_hash":state_digest(st.state()),"decision":canonical(st.last_decision)}
            expected={"intent":p["intent"],"state_after_hash":p["state_after_hash"],"decision":p["decision"]}
            checked+=1
            if actual != expected:
                mismatches.append({"时点":time,"策略":name,"实际重放":actual,"记录":expected})
        trade_count,amount=conn.execute("SELECT count(*),coalesce(sum(price*volume),0) FROM trades WHERE substr(time,1,10)=?",(day.isoformat(),)).fetchone()
        return {"日期":str(day),"核对方式":"逐次实际输入与状态重放","决策层_时点数":checked,
                "决策层_不一致":len(mismatches),"不一致样例":mismatches[:20],
                "执行层":{"实际成交笔数":trade_count,"实际成交额":round(amount,2)},
                "说明":"核对决策确定性；不将模拟成交或收益相等作为实盘成交的证明"}
    finally:
        conn.close()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default="executor/config.toml")
    ap.add_argument("--db",required=True); ap.add_argument("--date",required=True); ap.add_argument("--data-dir")
    args=ap.parse_args()
    cfg=tomllib.loads(resolve(args.config).read_text(encoding="utf-8"))
    report=replay_day(cfg,resolve(args.db),None,date.fromisoformat(args.date))
    out=resolve(cfg["engine"].get("runtime_dir","storage/executor_v2"))/"replay_checks"/f"{args.date}.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
