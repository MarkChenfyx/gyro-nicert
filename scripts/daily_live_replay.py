"""Capture today's vn.py state and run the daily live reconciliation."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.common.time_utils import now_beijing
from backend.services import live_service


def main() -> int:
    today = now_beijing().date().isoformat()
    status = live_service.local_source_status()
    if not status.get("available"):
        print(f"[ERROR] 本机实盘目录不可用：{status.get('message', '')}")
        return 1

    state_date = str(status.get("state_trade_date") or "")
    if state_date != today:
        print(f"[SKIP] 状态文件对应 {state_date or '未知日期'}，今天是 {today}；休市或状态尚未更新。")
        return 0

    sources = [
        item for item in live_service.list_sources()
        if str(item.get("source_kind") or "") == live_service.SOURCE_KIND_LOCAL
    ]
    if not sources:
        print("[ERROR] 尚未建立本机实盘源，请先在网页完成第一次建立。")
        return 1

    failed = False
    for source in sources:
        source_id = str(source["source_id"])
        name = str(source.get("name") or source_id)
        try:
            live_service.import_snapshot(source_id, {"trade_date": today})
            record = live_service.track_day(source_id, today, update_data=True)
            summary = dict(record.get("summary") or {})
            print(
                f"[OK] {name} {today}：策略 {summary.get('total', 0)}，"
                f"一致 {summary.get('match', 0)}，差异 {summary.get('mismatch', 0)}，"
                f"回放成交 {summary.get('trade_count', 0)}"
            )
        except Exception as exc:  # Task Scheduler needs a concise persistent failure message.
            failed = True
            print(f"[ERROR] {name} {today}：{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
