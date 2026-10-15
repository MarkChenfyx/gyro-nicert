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

from .clock import RealClock, SimClock
from .data import iter_quotes, load_actions
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
        db.unlink()
    store = Store(db, run_dir / "logs")
    risk = RiskManager(RiskConfig(**{**risk_cfg, "stop_file": ""}))
    engine = Engine(clock=clock, market_gw=ReplayMarket(), trade_gw=broker, strategies=strategies, capitals=capitals,
                    store=store, risk=risk, tplus1=tplus1, commission_bp=eng.get("commission_bp", 1.0),
                    max_quote_age=eng.get("max_quote_age_seconds", 90.0), actions=actions)
    engine.start()
    symbols = sorted({s for st in strategies for s in st.symbols})
    for t, quotes in iter_quotes(data_dir, symbols, start, end):
        engine.on_quotes(t, quotes)
    engine.finish()
    report = summarize(db, data_dir, cfg["strategy"], start, end)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def run_realtime(cfg: dict, mode: str) -> None:
    from .gateways.qmt import QmtGateway

    eng, risk_cfg, qmt = cfg["engine"], cfg.get("risk", {}), cfg.get("qmt", {})
    live = mode == "live" and bool(eng.get("live_trading", False))
    if mode == "live" and not live:
        raise SystemExit("mode = live 但 live_trading 不是 true，拒绝启动真实下单。纸面运行请用 mode = paper。")
    runtime = resolve(eng.get("runtime_dir", "storage/executor"))
    strategies = build_strategies(cfg)
    capitals = {s["name"]: float(s["capital"]) for s in cfg["strategy"]}
    tplus1 = set(eng.get("tplus1", []))
    clock = RealClock()
    gateway = QmtGateway(qmt.get("userdata_path", ""), qmt.get("account_id", ""), allow_orders=live)
    gateway.connect()
    if live:
        trade_gw = gateway
        store = Store(runtime / "live.sqlite", runtime / "logs" / "live")
    else:
        sim = cfg.get("sim", {})
        trade_gw = SimBroker(clock, sum(capitals.values()), sim.get("latency_seconds", 1.0), eng.get("commission_bp", 1.0),
                             tplus1=tplus1)
        store = Store(runtime / "paper.sqlite", runtime / "logs" / "paper")
    risk_cfg = {**risk_cfg, "stop_file": str(resolve(risk_cfg.get("stop_file", "storage/executor/STOP")))}
    recorder = Recorder(resolve(eng.get("data_dir", "storage/executor/ticks")))
    engine = Engine(clock=clock, market_gw=gateway, trade_gw=trade_gw, strategies=strategies, capitals=capitals,
                    store=store, risk=RiskManager(RiskConfig(**risk_cfg)), tplus1=tplus1,
                    commission_bp=eng.get("commission_bp", 1.0), max_quote_age=eng.get("max_quote_age_seconds", 90.0),
                    recorder=recorder, state_save_every=eng.get("state_save_every", 6))
    problems = engine.start()
    if problems:
        print("核对未通过，本次只接行情不交易：", problems)
    stopping = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stopping.update(flag=True))
    try:
        engine.run_live(lambda: stopping["flag"])
    finally:
        recorder.flush()
        gateway.close()


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
        run_dir = resolve(cfg["engine"].get("runtime_dir", "storage/executor")) / "backtests" / args.run_name
        report = run_backtest(cfg, datetime.fromisoformat(args.start), datetime.fromisoformat(args.end), data_dir, run_dir)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
        print("结果目录：", run_dir)
    else:
        run_realtime(cfg, mode)


if __name__ == "__main__":
    main()
