from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - fallback for minimal Windows Python installs.
    BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ).replace(microsecond=0)


def now_iso() -> str:
    return now_beijing().isoformat()


def timestamp_id() -> str:
    return now_beijing().strftime("%Y%m%d_%H%M%S")
