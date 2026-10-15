"""从 RQData 下载引擎回测用的 tick（每分钟最后一个快照）和除权除息表，写到 storage/executor/ticks（或 --data-dir）。

  python scripts/executor_download_ticks.py --config executor/config.example.toml --start 2024-01-01 --end 2026-10-14

按月下载，已存在的月份跳过；每个标的每月约 0.4MB 流量，注意 RQData 每日流量上限。
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.data_manager.rqdata_client import get_default_client  # noqa: E402
from executor.data import write_quotes  # noqa: E402
from executor.runner import resolve  # noqa: E402


def rq_id(symbol: str) -> str:
    code, ex = symbol.split(".")
    return f"{code}.{'XSHG' if ex == 'SH' else 'XSHE'}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="executor/config.toml")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--data-dir")
    args = ap.parse_args()
    cfg = tomllib.loads(resolve(args.config).read_text(encoding="utf-8"))
    data_dir = Path(args.data_dir) if args.data_dir else resolve(cfg["engine"].get("data_dir", "storage/executor/ticks"))
    symbols = sorted({s for st in cfg["strategy"] for s in st["symbols"]})
    get_default_client().init()
    import rqdatac

    for symbol in symbols:
        for start in pd.date_range(args.start, args.end, freq="MS"):
            name = f"{start:%Y-%m}"
            if (data_dir / symbol / f"{name}.pkl").exists():
                continue
            end = min(start + pd.offsets.MonthEnd(0), pd.Timestamp(args.end))
            t = rqdatac.get_price(rq_id(symbol), start, end, "tick", fields=["last", "a1", "b1", "iopv"])
            if t is None or t.empty:
                continue
            t = t.droplevel(0)
            t = t[(t.a1 > 0) & (t.b1 > 0)]
            t = t[(t.index.time >= pd.Timestamp("09:30").time()) & (t.index.time <= pd.Timestamp("15:00").time())]
            m = t.groupby(t.index.ceil("min")).last().rename(columns={"a1": "ask1", "b1": "bid1"})
            write_quotes(data_dir, symbol, name, m)
            print(symbol, name, len(m), round(rqdatac.user.get_quota()["bytes_used"] / 1e6), "MB", flush=True)

    rows = []
    for symbol in symbols:
        ex = rqdatac.get_ex_factor(rq_id(symbol))
        if ex is None or len(ex) < 2:
            continue
        ex = ex.reset_index().sort_values("ex_date")
        prices = rqdatac.get_price(rq_id(symbol), args.start, args.end, "1d", fields=["close"], adjust_type="none")
        close = prices.droplevel(0).close if prices is not None else pd.Series(dtype=float)
        for prev, cur in zip(ex.itertuples(), ex.iloc[1:].itertuples()):
            ratio = cur.ex_cum_factor / prev.ex_cum_factor
            d = pd.Timestamp(cur.ex_date)
            before = close[close.index < d]
            if d < pd.Timestamp(args.start) or before.empty:
                continue
            if ratio >= 1.5:
                rows.append((d.date(), symbol, 0.0, round(ratio, 6)))
            elif ratio > 1:
                rows.append((d.date(), symbol, round(before.iloc[-1] * (1 - 1 / ratio), 6), 1.0))
    pd.DataFrame(rows, columns=["date", "symbol", "cash_per_share", "split_ratio"]).to_csv(data_dir / "corporate_actions.csv", index=False)
    print("除权除息记录", len(rows))


if __name__ == "__main__":
    main()
