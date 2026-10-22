"""启动入口。

  python -m executor.runner --config executor/config.toml                         按配置里的 mode 运行
  python -m executor.runner --config executor/config.example.toml --mode backtest \\
      --start 2024-01-01 --end 2026-04-15 --data-dir <行情目录> --run-name test   回测

回测结果写到 <runtime_dir>/backtests/<run-name>/（数据库、流水、report.json），不影响实盘记录。
实盘真实下单需要 mode = "live" 且配置 live_trading = true，二者缺一不可。
"""
from __future__ import annotations

import argparse
import json
import signal
import tomllib
from datetime import datetime
from pathlib import Path

from .clock import RealClock, SimClock, beijing_now
from .data import iter_events, load_actions
from .engine import Engine
from .gateways.sim import ReplayMarket, SimBroker
from .recorder import Recorder
from .report import summarize
from .risk import RiskConfig, RiskManager
from .store import Store
from .strategies.same_index_rotation import SameIndexRotation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_TYPES = {"same_index_rotation": SameIndexRotation}


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def build_strategies(cfg: dict) -> list:
    out = []
    for s in cfg.get("strategy", []):
        params = {k: v for k, v in s.items() if k not in ("type", "capital")}
        out.append(STRATEGY_TYPES[s["type"]](**params))
    return out


def run_backtest(cfg: dict, start: datetime, end: datetime, data_dir: Path, run_dir: Path) -> dict:
    eng, sim, risk_cfg = cfg["engine"], cfg.get("sim", {}), cfg.get("risk", {})
    strategies = build_strategies(cfg)
    capitals = {s["name"]: float(s["capital"]) for s in cfg["strategy"]}
    actions = load_actions(data_dir)
    tplus1 = set(eng.get("tplus1", []))
    clock = SimClock()
    broker = SimBroker(clock, sum(capitals.values()), sim.get("latency_seconds", 0.0), eng.get("commission_bp", 1.0),
                       fill_ratio=sim.get("fill_ratio", 1.0), reject_rate=sim.get("reject_rate", 0.0),
                       tplus1=tplus1, actions=actions)
    run_dir.mkdir(parents=True, exist_ok=True)
    db = run_dir / "executor.sqlite"
    if db.exists():
        raise FileExistsError("已有同名运行，禁止覆盖，请使用新的 run-name")
    store = Store(db, run_dir / "logs")
    risk = RiskManager(RiskConfig(**{**risk_cfg, "stop_file": ""}))
    engine = Engine(clock=clock, market_gw=ReplayMarket(), trade_gw=broker, strategies=strategies, capitals=capitals,
                    store=store, risk=risk, tplus1=tplus1, commission_bp=eng.get("commission_bp", 1.0),
                    max_quote_age=eng.get("max_quote_age_seconds", 90.0), actions=actions, snapshot_wait_seconds=eng.get("snapshot_wait_seconds", 2.0))
    try:
        problems = engine.start()
        if problems:
            raise RuntimeError("模拟账户核对失败：" + "；".join(problems))
        symbols = sorted({s for st in strategies for s in st.symbols})
        for kind, t, quotes in iter_events(data_dir, symbols, start, end):
            if kind == "quotes":
                engine.on_quotes(t, quotes)
            else:
                engine.on_timer(t)
        engine.finish()
    finally:
        store.close()
    report = summarize(db, data_dir, cfg["strategy"], start, end)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


EVENT_LABELS = {"start": "启动", "intent": "新目标", "intent_done": "换仓完成", "intent_expired": "换仓过期",
                "intent_blocked": "目标被拦截", "order_blocked": "委托被风控拦截", "order_rejected": "委托被拒",
                "trade": "成交", "gateway_down": "暂停交易", "broker_query_failed": "券商查询失败",
                "corporate_action": "除权除息", "corporate_action_mismatch": "除权数据不一致，相关策略今日暂停",
                "corporate_action_source_failed": "读取除权数据失败"}


def console(text: str) -> None:
    print(f"[{beijing_now():%m-%d %H:%M:%S}] {text}", flush=True)


def popup(title: str, body: str) -> None:
    """Windows 弹窗提醒（不阻塞引擎）；非 Windows 或失败时只在窗口打印。"""
    import os
    import subprocess
    if os.name != "nt":
        return
    script = ("Add-Type -AssemblyName PresentationFramework;"
              f"[System.Windows.MessageBox]::Show('{body.replace(chr(39), chr(39) * 2)}','{title}') | Out-Null")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script])
    except OSError:
        pass


def show_event(t, kind: str, strategy: str, payload: dict) -> None:
    if kind not in EVENT_LABELS:
        return
    detail = json.dumps(payload, ensure_ascii=False, default=str)
    console(f"{EVENT_LABELS[kind]} {strategy} {detail[:300]}".replace("  ", " "))
    if kind == "gateway_down" or (kind == "start" and not payload.get("trading_enabled")):
        reason = payload.get("message") or "；".join(payload.get("problems") or [])
        popup("交易引擎已暂停交易", f"{reason}（新委托已停止，请查看引擎窗口）")
    elif kind in ("corporate_action_mismatch", "corporate_action_source_failed"):
        popup("交易引擎：除权数据需核对", f"{EVENT_LABELS[kind]} {detail[:200]}")


def run_realtime(cfg: dict, mode: str) -> None:
    from .gateways.qmt import QmtMarketGateway, QmtTradeGateway

    eng, risk_cfg, qmt = cfg["engine"], cfg.get("risk", {}), cfg.get("qmt", {})
    live = mode == "live" and bool(eng.get("live_trading", False))
    if mode == "live" and not live:
        raise SystemExit("mode = live 但 live_trading 不是 true，拒绝启动真实下单")
    if live and qmt.get("account_mode", "dedicated") != "dedicated":
        raise ValueError("当前实盘只支持专用资金账户；共用账户需先接入统一资源协调")
    runtime = resolve(eng.get("runtime_dir", "storage/executor_v2"))
    strategies = build_strategies(cfg)
    capitals = {s["name"]: float(s["capital"]) for s in cfg["strategy"]}
    tplus1 = set(eng.get("tplus1", []))
    clock = RealClock()
    market = QmtMarketGateway()
    account = QmtTradeGateway(qmt.get("userdata_path", ""), qmt.get("account_id", ""), allow_orders=True) if live else None
    store = None
    recorder = Recorder(resolve(eng.get("recording_dir", "storage/executor_v2/recordings")))
    try:
        if account is not None:  # 纸面模式不登录交易账户，账户上其他程序的委托和成交不会进入引擎
            account.connect()
        store = Store(runtime / ("live.sqlite" if live else "paper.sqlite"), runtime / "logs" / mode)
        store.listener = show_event
        console(f"交易引擎启动：{'实盘' if live else '纸面'}模式，{len(strategies)} 个策略；每分钟显示一次状态，Ctrl+C 停止")
        restoring = bool(store.load_runtime("engine"))
        sim = cfg.get("sim", {})
        trade_gw = account if live else SimBroker(clock, sum(capitals.values()), sim.get("latency_seconds", 1.0),
            eng.get("commission_bp", 1.0), fill_ratio=sim.get("fill_ratio", 1.0),
            reject_rate=sim.get("reject_rate", 0.0), tplus1=tplus1)
        risk_cfg = {**risk_cfg, "stop_file": str(resolve(risk_cfg.get("stop_file", "storage/executor/STOP")))}
        symbols = sorted({symbol for st in strategies for symbol in st.subscription().symbols})
        engine = Engine(clock=clock, market_gw=market, trade_gw=trade_gw, strategies=strategies, capitals=capitals,
            action_source=lambda day: market.corporate_actions(symbols, day),
            store=store, risk=RiskManager(RiskConfig(**risk_cfg)), tplus1=tplus1,
            commission_bp=eng.get("commission_bp", 1.0), max_quote_age=eng.get("max_quote_age_seconds", 90.0),
            recorder=recorder, snapshot_wait_seconds=eng.get("snapshot_wait_seconds", 2.0))
        problems = engine.start()
        if problems:
            print("核对未通过，本次只接行情不交易：", problems)
        if not getattr(market, "connected", True):
            console(f"QMT 行情暂未就绪（{market.last_error}），引擎会每分钟重试，QMT 启动后自动接上")
        if not restoring and eng.get("warmup_start") and eng.get("warmup_end"):
            symbols = sorted({symbol for sub in engine.subscriptions.values() for symbol in sub.symbols})
            console("正在用历史行情预热策略……")
            store.listener = None  # 预热期间的大量历史事件不刷屏
            engine.warmup(iter_events(resolve(eng["data_dir"]), symbols,
                datetime.fromisoformat(eng["warmup_start"]), datetime.fromisoformat(eng["warmup_end"])))
            store.listener = show_event
        stopping = {"flag": False}
        signal.signal(signal.SIGINT, lambda *_: stopping.update(flag=True))
        engine.run_live(lambda: stopping["flag"], console=console)
        console("交易引擎已停止，状态已保存")
    finally:
        recorder.flush()
        market.close()
        if account is not None:
            account.close()
        if store is not None:
            store.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="executor/config.toml")
    ap.add_argument("--mode", choices=["backtest", "paper", "live"])
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--data-dir")
    ap.add_argument("--run-name", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--latency", type=float)
    args = ap.parse_args()
    cfg = tomllib.loads(resolve(args.config).read_text(encoding="utf-8"))
    mode = args.mode or cfg["engine"].get("mode", "backtest")
    if args.latency is not None:
        cfg.setdefault("sim", {})["latency_seconds"] = args.latency
    if mode == "backtest":
        data_dir = Path(args.data_dir) if args.data_dir else resolve(cfg["engine"].get("data_dir", "storage/executor/ticks"))
        import re
        if not re.fullmatch(r"[\w-]+", args.run_name):
            raise ValueError("run-name 只能包含字母、数字、下划线和连字符")
        run_dir = resolve(cfg["engine"].get("runtime_dir", "storage/executor_v2")) / "backtests" / args.run_name
        report = run_backtest(cfg, datetime.fromisoformat(args.start), datetime.fromisoformat(args.end), data_dir, run_dir)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
        print("结果目录：", run_dir)
    else:
        run_realtime(cfg, mode)


if __name__ == "__main__":
    main()
