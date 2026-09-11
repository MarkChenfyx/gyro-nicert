"""单日回放子进程。

给定一份策略代码、它在前一交易日收盘时的真实状态，以及一个目标交易日，
本模块在独立进程里重放该交易日，输出收盘持仓与当日成交。

关键在于顺序：策略的指标（均线、ATR 等）依赖几百天的历史 K 线，实盘存档里没有，
只能靠预热重新算出来；而 pos、追踪止损这类变量实盘存档里有，必须原样灌入。
预热过程会覆盖这些变量，所以状态注入必须发生在预热之后、开始交易之前——
即 BacktestingEngine.run_backtesting 提供的 on_ready 时机。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
import json
import inspect
import math
import os
import sys


# 实盘 on_init 里最多加载 300 天，预热区间必须与实盘一致，
# 否则 EMA 这类有长期记忆的指标算不出相同的值。
WARMUP_DAYS = 300

# 这两个由引擎控制回放阶段，绝不能被存档状态覆盖。
BLOCKED_STATE_FIELDS = {"inited", "trading"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _load_class(path: Path, class_name: str):
    module_name = f"gyro_replay_{path.stem}_{os.getpid()}"
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载策略文件：{path.name}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    strategy_class = getattr(module, class_name, None)
    if strategy_class is None:
        raise ValueError(f"策略类不存在：{class_name}")
    return strategy_class


def replay_data_issue(bars: list[Any], start: date, end: date, exchange: str) -> str:
    """Conservative cash-market minute check; uncertain closures must not yield MATCH."""
    if exchange not in {"SSE", "SZSE"}:
        return "当前实盘分钟完整性校验仅支持沪深市场"
    by_day: dict[date, set[time]] = {}
    count_by_day: dict[date, int] = {}
    for bar in bars:
        day = bar.datetime.date()
        by_day.setdefault(day, set()).add(bar.datetime.time().replace(second=0, microsecond=0))
        count_by_day[day] = count_by_day.get(day, 0) + 1
    day = start
    while day <= end:
        if day.weekday() < 5:
            observed = by_day.get(day, set())
            # Accept either minute-start or minute-end timestamps, never mixed sessions.
            valid = False
            for offset in (0, 1):
                expected = {
                    (datetime.combine(day, opening) + timedelta(minutes=i + offset)).time()
                    for opening in (time(9, 30), time(13, 0)) for i in range(120)
                }
                if expected.issubset(observed) and count_by_day.get(day) == len(observed):
                    valid = True
            if not valid:
                return f"{day} 分钟行情不完整或无法确认停市（{len(observed)} 根）；本次不判断持仓一致性"
        day += timedelta(days=1)
    if end not in by_day:
        return "目标日没有行情，无法确认该日收盘持仓"
    return ""


def _state_injector(prior_state: dict[str, Any], applied: list[str], skipped: list[str]):
    def inject(strategy: Any) -> None:
        # 参数由 add_strategy 按实盘配置设定，存档状态不得覆盖它们。
        blocked = BLOCKED_STATE_FIELDS | set(getattr(strategy, "parameters", []) or [])
        for name, value in prior_state.items():
            if name in blocked or not hasattr(strategy, name):
                skipped.append(str(name))
                continue
            setattr(strategy, name, value)
            applied.append(str(name))

    return inject


def _scalars(values: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded scalar evidence; never serialize models, arrays or object reprs."""
    result = {}
    for name, value in values.items():
        if name.startswith("_"):
            continue
        if hasattr(value, "item") and getattr(value, "ndim", None) == 0:
            value = value.item()
        if value is None or isinstance(value, (bool, int)):
            result[name] = value
        elif isinstance(value, float) and math.isfinite(value):
            result[name] = value
        elif isinstance(value, str) and len(value) <= 200:
            result[name] = value
    return result


def _bar_evidence(bar: Any) -> dict[str, Any]:
    if bar is None or not hasattr(bar, "close_price"):
        return {}
    return {key: _json_safe(getattr(bar, key, None)) for key in
            ("datetime", "open_price", "high_price", "low_price", "close_price", "volume")}


class ReplayTrace:
    """Observe submissions and fills in the replay process without changing the matching engine."""

    def __init__(self, engine: Any, strategy_path: Path):
        self.engine = engine
        self.path = strategy_path.resolve()
        self.lines = strategy_path.read_text(encoding="utf-8-sig").splitlines()
        self.signals: list[dict[str, Any]] = []
        self.fills: dict[str, dict[str, Any]] = {}
        original_send = engine.send_order
        original_trade = engine.strategy.on_trade

        def send(strategy, direction, offset, price, volume, stop, lock, net):
            evidence = self.evidence(strategy)
            ids = original_send(strategy, direction, offset, price, volume, stop, lock, net)
            self.signals.append({
                "signal_id": f"signal_{len(self.signals) + 1}",
                "datetime": _json_safe(engine.datetime), "order_ids": list(ids),
                "direction": direction.value, "offset": offset.value,
                "requested_price": price, "volume": volume, "order_type": "停止单" if stop else "限价单",
                "position_at_signal": strategy.pos, **evidence,
            })
            return ids

        def trade(trade):
            after = float(engine.strategy.pos)
            change = float(trade.volume) if trade.direction.value == "多" else -float(trade.volume)
            self.fills[str(trade.tradeid)] = {
                "position_before": after - change, "position_after": after,
                "fill_bar": _bar_evidence(engine.bar), "vt_orderid": trade.vt_orderid,
            }
            return original_trade(trade)

        engine.send_order = send
        engine.strategy.on_trade = trade

    def evidence(self, strategy: Any) -> dict[str, Any]:
        declared = set(getattr(strategy, "variables", [])) | set(getattr(strategy, "parameters", []))
        values = {key: value for key, value in vars(strategy).items()
                  if key in declared or isinstance(value, (int, float, bool))}
        for name in declared:
            if name not in values and hasattr(strategy, name):
                values[name] = getattr(strategy, name)
        contexts = []
        frame = inspect.currentframe()
        try:
            while frame is not None and len(contexts) < 3:
                if Path(frame.f_code.co_filename).resolve() == self.path:
                    line = frame.f_lineno
                    contexts.append({
                        "function": frame.f_code.co_name, "line": line,
                        "code": "\n".join(f"{i + 1}: {self.lines[i]}" for i in range(max(0, line - 7), min(len(self.lines), line + 2))),
                        "locals": _scalars(frame.f_locals),
                        "bar": _bar_evidence(frame.f_locals.get("bar")),
                    })
                frame = frame.f_back
        finally:
            del frame
        return {"variables": _scalars(values), "contexts": contexts,
                "source_file": self.path.name, "input_bar": _bar_evidence(self.engine.bar)}

    def finish(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        orders = []
        linked = {}
        for signal in self.signals:
            for submitted_id in signal["order_ids"]:
                stop = self.engine.stop_orders.get(submitted_id)
                order = stop or self.engine.limit_orders.get(submitted_id)
                child_ids = list(stop.vt_orderids) if stop else [submitted_id]
                for child in child_ids:
                    linked[child] = signal["signal_id"]
                if order is not None:
                    orders.append({
                        "order_id": submitted_id, "signal_id": signal["signal_id"],
                        "datetime": signal["datetime"], "order_type": signal["order_type"],
                        "direction": signal["direction"], "offset": signal["offset"],
                        "price": order.price, "volume": order.volume,
                        "status": order.status.value, "child_order_ids": child_ids,
                    })
        enriched = []
        for trade in trades:
            fill = self.fills.get(str(trade["tradeid"]), {})
            enriched.append({**trade, **fill, "signal_id": linked.get(fill.get("vt_orderid"), "")})
        return {"trades": enriched, "orders": orders, "signals": self.signals, "trace_version": 1}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    from vnpy.trader.constant import Interval
    from vnpy_ctastrategy.base import BacktestingMode

    from backend.backtesting.local_data_provider import load_bar_data
    from backend.backtesting.run import (
        _resource_dir,
        _local_bar_loader,
        _trade_records,
        _unsupported_tick_loader,
    )
    from backend.backtesting.cta_engine import BacktestingEngine

    package_root = Path(payload["package_root"]).resolve()
    resource_root = Path(payload.get("resource_root") or package_root).resolve()
    if not resource_root.is_dir():
        raise FileNotFoundError(f"回放资源目录不存在：{resource_root}")
    strategy_path = (package_root / str(payload["module_path"])).resolve()
    strategy_path.relative_to(package_root)
    if not strategy_path.is_file():
        raise FileNotFoundError(f"策略文件不存在：{payload['module_path']}")

    end_date = date.fromisoformat(str(payload["end_date"])[:10])
    start_date = date.fromisoformat(str(payload.get("start_date") or payload["end_date"])[:10])
    if start_date > end_date:
        raise ValueError(f"回放起始日 {start_date} 晚于结束日 {end_date}")
    vt_symbol = str(payload["vt_symbol"])
    # start 定在起始日零点，引擎的预热区间 [start - WARMUP_DAYS, start) 因而自动落在此前的历史上。
    start = datetime.combine(start_date, time(0, 0, 0))
    end = datetime.combine(end_date, time(23, 59, 59))

    bars = load_bar_data(vt_symbol, "1m", start, end)
    issue = replay_data_issue(bars, start_date, end_date, vt_symbol.rsplit(".", 1)[-1])
    if issue:
        return {"success": False, "reason": "no_bars", "error": issue}
    if not bars:
        # 行情缺失不是回放本身的故障，交给调用方归入 DATA_GAP。
        return {
            "success": False,
            "reason": "no_bars",
            "error": f"{start_date.isoformat()} 至 {end_date.isoformat()} 没有 {vt_symbol} 的一分钟行情",
        }

    applied: list[str] = []
    skipped: list[str] = []
    injector = _state_injector(dict(payload.get("prior_state") or {}), applied, skipped)

    # 策略包内的模型文件按相对路径加载，整段回放都在包目录下执行。
    with _resource_dir(resource_root):
        strategy_class = _load_class(strategy_path, str(payload["class_name"]))

        engine = BacktestingEngine()
        engine.set_data_loaders(bar_loader=_local_bar_loader, tick_loader=_unsupported_tick_loader)
        engine.set_parameters(
            vt_symbol=vt_symbol, interval=Interval.MINUTE, start=start, end=end,
            rate=float(payload.get("rate", 0.000045)), slippage=float(payload.get("slippage", 0.001)),
            size=float(payload.get("size", 1)), pricetick=float(payload.get("pricetick", 0.001)),
            capital=int(float(payload.get("capital", 100000))), mode=BacktestingMode.BAR,
        )
        # 参数按实盘原样传入，不做 fixed_size 归一化：对账要的是与实盘同量纲的手数。
        engine.add_strategy(strategy_class, dict(payload.get("parameters") or {}))
        # Some deployed strategies warm up in on_start. Restore again after it finishes.
        original_start = engine.strategy.on_start
        def start_and_restore() -> None:
            original_start()
            injector(engine.strategy)
        engine.strategy.on_start = start_and_restore
        trace = ReplayTrace(engine, strategy_path)
        engine.history_data = bars
        engine.run_backtesting(on_ready=injector)

    strategy = engine.strategy
    end_variables = {
        name: _json_safe(getattr(strategy, name, None))
        for name in (getattr(strategy, "variables", []) or [])
    }
    return {
        "success": True,
        "end_pos": float(strategy.pos),
        "end_variables": end_variables,
        **_json_safe(trace.finish(_trade_records(engine.get_all_trades()))),
        "bar_count": len(bars),
        "replay_start": start_date.isoformat(),
        "replay_end": end_date.isoformat(),
        "state_applied": applied,
        "state_skipped": skipped,
        "state_unrestored": sorted(set(skipped) - BLOCKED_STATE_FIELDS - set(getattr(strategy, "parameters", []))),
        "logs": list(engine.logs[-50:]),
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m backend.backtesting.replay_worker INPUT OUTPUT")
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    try:
        result = run(json.loads(input_path.read_text(encoding="utf-8")))
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    output_path.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
