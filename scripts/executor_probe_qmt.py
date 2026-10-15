"""在服务器上只读探测 QMT 接口（不下单）：打印行情字段（重点看有没有 IOPV）、持仓和资金。

用 VeighNa / QMT 所在的 Python 运行，交易时间内运行最有意义：
  python scripts/executor_probe_qmt.py --userdata "D:\\国金QMT交易端\\userdata_mini" --account 资金账号
不填 --account 时只测行情。
"""
from __future__ import annotations

import argparse
import time

SYMBOLS = ["513530.SH", "513820.SH", "513520.SH", "159920.SZ", "159892.SZ"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--userdata", default="")
    ap.add_argument("--account", default="")
    args = ap.parse_args()

    from xtquant import xtdata

    print("== 行情 ==")
    for s in SYMBOLS:
        xtdata.subscribe_quote(s, period="tick", count=1)
    time.sleep(3)
    ticks = xtdata.get_full_tick(SYMBOLS)
    for code, tick in ticks.items():
        keys = sorted(tick.keys())
        iopv_like = {k: tick[k] for k in keys if "iopv" in k.lower() or "nav" in k.lower()}
        print(code, "字段：", keys)
        print("   最新价", tick.get("lastPrice"), "买一", (tick.get("bidPrice") or [None])[0], "卖一", (tick.get("askPrice") or [None])[0],
              "时间", tick.get("time"), "疑似 IOPV 字段", iopv_like or "无")

    received = []
    xtdata.subscribe_whole_quote(SYMBOLS, callback=lambda data: received.append(data))
    time.sleep(10)
    print(f"全推回调 10 秒内收到 {len(received)} 次")
    if received:
        code, tick = next(iter(received[-1].items()))
        print("回调样例", code, {k: tick[k] for k in sorted(tick)[:40]})

    if args.account and args.userdata:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount

        print("== 账户（只读）==")
        trader = XtQuantTrader(args.userdata, int(time.time()))
        trader.start()
        print("连接结果", trader.connect())
        acc = StockAccount(args.account)
        print("订阅结果", trader.subscribe(acc))
        asset = trader.query_stock_asset(acc)
        print("资金", getattr(asset, "cash", None), "总资产", getattr(asset, "total_asset", None))
        for p in trader.query_stock_positions(acc) or []:
            print("持仓", p.stock_code, p.volume, "可用", p.can_use_volume)
        orders = trader.query_stock_orders(acc, False) or []
        print(f"当日委托 {len(orders)} 笔；样例字段：", sorted(a for a in dir(orders[0]) if not a.startswith("_")) if orders else "无")
        trader.stop()


if __name__ == "__main__":
    main()
