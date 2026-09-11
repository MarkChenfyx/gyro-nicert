"""In-process weekday scheduler for live snapshots and replay reconciliation."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.common.time_utils import BEIJING_TZ, now_beijing, now_iso
from backend.core.environment import env
from backend.core.paths import RUNTIME_ROOT
from backend.repositories import live_repository
from backend.services import live_service


AUTO_ENABLED_ENV = "GYRO_LIVE_AUTO_TRACK"
AUTO_TIME_ENV = "GYRO_LIVE_AUTO_TIME"
DEFAULT_RUN_TIME = time(15, 20)
STATUS_PATH = RUNTIME_ROOT / "live_scheduler_status.json"
CHECK_INTERVAL_SECONDS = 60
STARTUP_DELAY_SECONDS = 3


def enabled() -> bool:
    return env(AUTO_ENABLED_ENV, "true").lower() not in {"0", "false", "no", "off"}


def run_time() -> time:
    raw = env(AUTO_TIME_ENV, DEFAULT_RUN_TIME.strftime("%H:%M"))
    try:
        hour, minute = (int(part) for part in raw.split(":"))
        return time(hour, minute)
    except (TypeError, ValueError):
        return DEFAULT_RUN_TIME


def _read_status() -> dict[str, Any]:
    if not STATUS_PATH.is_file():
        return {}
    try:
        value = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_status(value: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_name(f".{STATUS_PATH.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATUS_PATH)


def _scheduled_at(day: date) -> datetime:
    return datetime.combine(day, run_time(), tzinfo=BEIJING_TZ)


def _next_run(now: datetime, last_attempt_date: str) -> datetime:
    day = now.date()
    if day.weekday() < 5 and last_attempt_date != day.isoformat() and now < _scheduled_at(day):
        return _scheduled_at(day)
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return _scheduled_at(day)


def status() -> dict[str, Any]:
    now = now_beijing()
    saved = _read_status()
    active = enabled()
    last_date = str(saved.get("last_attempt_date") or "")
    due = active and now.weekday() < 5 and now >= _scheduled_at(now.date()) and last_date != now.date().isoformat()
    return {
        "enabled": active,
        "schedule_time": run_time().strftime("%H:%M"),
        "timezone": "Asia/Shanghai",
        "due": due,
        "next_run_at": _next_run(now, last_date).isoformat() if active else "",
        **saved,
    }


def should_run(now: datetime | None = None) -> bool:
    current = now or now_beijing()
    saved = _read_status()
    attempted_today = (
        str(saved.get("last_attempt_date") or "") == current.date().isoformat()
        and str(saved.get("last_status") or "") != "running"
    )
    return (
        enabled()
        and current.weekday() < 5
        and current >= _scheduled_at(current.date())
        and not attempted_today
    )


def run_today(now: datetime | None = None) -> dict[str, Any]:
    current = now or now_beijing()
    trade_date = current.date().isoformat()
    started = {
        "last_attempt_date": trade_date,
        "last_started_at": now_iso(),
        "last_finished_at": "",
        "last_status": "running",
        "last_message": "正在读取实盘状态并执行回放",
        "last_results": [],
    }
    _write_status(started)

    try:
        local = live_service.local_source_status()
        if not local.get("available"):
            raise RuntimeError(str(local.get("message") or "本机实盘目录不可用"))
        state_date = str(local.get("state_trade_date") or "")
        if state_date != trade_date:
            result = {
                **started,
                "last_finished_at": now_iso(),
                "last_status": "skipped",
                "last_message": f"状态文件对应 {state_date or '未知日期'}；今天休市或状态尚未更新",
            }
            _write_status(result)
            return result

        sources = [
            item for item in live_service.list_sources()
            if str(item.get("source_kind") or "") == live_service.SOURCE_KIND_LOCAL
        ]
        if not sources:
            raise RuntimeError("尚未建立本机实盘源，请先在实盘跟踪页建立起点")

        rows: list[dict[str, Any]] = []
        failed = False
        for source in sources:
            source_id = str(source["source_id"])
            name = str(source.get("name") or source_id)
            try:
                live_service.import_snapshot(source_id, {"trade_date": trade_date})
                if live_repository.previous_snapshot(source_id, trade_date) is None:
                    rows.append({"source_id": source_id, "name": name, "status": "baseline", "message": "已保存首日基线快照"})
                    continue
                record = live_service.track_day(source_id, trade_date, update_data=True)
                summary = dict(record.get("summary") or {})
                rows.append({"source_id": source_id, "name": name, "status": "completed", "summary": summary})
            except Exception as exc:
                failed = True
                rows.append({"source_id": source_id, "name": name, "status": "failed", "message": str(exc)})

        result = {
            **started,
            "last_finished_at": now_iso(),
            "last_status": "failed" if failed else "completed",
            "last_message": "部分实盘源执行失败" if failed else "自动跟踪完成",
            "last_results": rows,
        }
    except Exception as exc:
        result = {
            **started,
            "last_finished_at": now_iso(),
            "last_status": "failed",
            "last_message": str(exc),
        }
    _write_status(result)
    return result


async def run_forever() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        if should_run():
            await asyncio.to_thread(run_today)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
