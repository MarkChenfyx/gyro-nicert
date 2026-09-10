"""为实盘跟踪补齐本地一分钟行情。

读取 vn.py 实盘配置里当前启用的策略，取出它们的标的，
逐个检查本地覆盖范围并按需下载。可重复运行：已覆盖的标的直接跳过。

用法：
    python scripts/download_live_symbols.py --setting <cta_strategy_setting.json> \
        --start 2025-08-01 --end 2026-09-02
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.backtesting.local_data_provider import split_vt_symbol  # noqa: E402
from backend.data_manager import coverage_service, download_service  # noqa: E402


def symbols_from_setting(path: Path) -> list[str]:
    settings = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for config in settings.values():
        vt_symbol = str((config or {}).get("vt_symbol") or "").strip()
        if "." in vt_symbol:
            found[vt_symbol] = found.get(vt_symbol, 0) + 1
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setting", required=True, help="cta_strategy_setting.json 路径")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="1m")
    args = parser.parse_args()

    symbols = symbols_from_setting(Path(args.setting))
    print(f"启用策略覆盖 {len(symbols)} 个标的，区间 {args.start} → {args.end}", flush=True)

    done: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for index, vt_symbol in enumerate(symbols, start=1):
        symbol, exchange = split_vt_symbol(vt_symbol)
        coverage = coverage_service.get_data_coverage(
            symbol, exchange, args.interval, start_date=args.start, end_date=args.end
        )
        if coverage.get("status") == "covered":
            print(f"[{index}/{len(symbols)}] {vt_symbol} 已覆盖，跳过", flush=True)
            skipped.append(vt_symbol)
            continue

        started = time.perf_counter()
        print(f"[{index}/{len(symbols)}] {vt_symbol} 开始下载 ...", flush=True)
        try:
            result = download_service.download_bars(
                symbol, exchange, args.interval, args.start, args.end
            )
        except Exception as exc:  # 单个标的失败不影响其余标的
            failed.append((vt_symbol, f"{type(exc).__name__}: {exc}"))
            print(f"[{index}/{len(symbols)}] {vt_symbol} 异常：{exc}", flush=True)
            continue

        elapsed = time.perf_counter() - started
        if result.get("success"):
            print(
                f"[{index}/{len(symbols)}] {vt_symbol} 完成 "
                f"{result.get('inserted', '?')} 根，用时 {elapsed:.1f}s",
                flush=True,
            )
            done.append(vt_symbol)
        else:
            reason = str(result.get("error") or "未知原因")
            failed.append((vt_symbol, reason))
            print(f"[{index}/{len(symbols)}] {vt_symbol} 失败：{reason}", flush=True)

    print("\n==== 汇总 ====", flush=True)
    print(f"下载成功 {len(done)}｜已有跳过 {len(skipped)}｜失败 {len(failed)}", flush=True)
    for vt_symbol, reason in failed:
        print(f"  失败 {vt_symbol}: {reason}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
