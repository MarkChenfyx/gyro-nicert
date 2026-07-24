from __future__ import annotations

from datetime import timedelta
from threading import Lock
from time import monotonic
from typing import Any

from backend.common.time_utils import now_beijing
from backend.core.environment import env
from backend.domain.enums import TaskStatus
from backend.repositories import task_repository


DEFAULT_TASK_STALE_HOURS = 6.0
STALE_SCAN_INTERVAL_SECONDS = 60.0
_stale_scan_lock = Lock()
_last_stale_scan_at = 0.0


def _configured_stale_hours() -> float:
    raw = env("GYRO_TASK_STALE_AFTER_HOURS", str(DEFAULT_TASK_STALE_HOURS))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TASK_STALE_HOURS


def cleanup_stale_tasks(*, force: bool = False, stale_after_hours: float | None = None) -> int:
    global _last_stale_scan_at
    scan_at = monotonic()
    if not force and scan_at - _last_stale_scan_at < STALE_SCAN_INTERVAL_SECONDS:
        return 0
    with _stale_scan_lock:
        scan_at = monotonic()
        if not force and scan_at - _last_stale_scan_at < STALE_SCAN_INTERVAL_SECONDS:
            return 0
        _last_stale_scan_at = scan_at
        stale_hours = _configured_stale_hours() if stale_after_hours is None else max(0.0, float(stale_after_hours))
        if stale_hours <= 0:
            return 0
        stale_before = (now_beijing() - timedelta(hours=stale_hours)).isoformat()
        return task_repository.reclaim_stale_tasks(stale_before, stale_hours=stale_hours)


def create_task(
    task_type: str,
    message: str | None = None,
    related_strategy_id: str | None = None,
    related_run_id: str | None = None,
    related_pool_item_id: str | None = None,
) -> dict[str, Any]:
    return task_repository.create_task(
        task_type,
        message=message,
        related_strategy_id=related_strategy_id,
        related_run_id=related_run_id,
        related_pool_item_id=related_pool_item_id,
    )


def mark_running(task_id: str, message: str | None = None) -> dict[str, Any]:
    return task_repository.update_task_status(
        task_id,
        TaskStatus.RUNNING.value,
        progress=0.0,
        message=message,
        error="",
    )


def mark_progress(task_id: str, progress: float, message: str | None = None) -> dict[str, Any]:
    normalized = max(0.0, min(1.0, float(progress)))
    return task_repository.update_task_status(
        task_id,
        TaskStatus.RUNNING.value,
        progress=normalized,
        message=message,
        error="",
    )


def mark_completed(task_id: str, message: str | None = None) -> dict[str, Any]:
    return task_repository.update_task_status(
        task_id,
        TaskStatus.COMPLETED.value,
        progress=1.0,
        message=message,
        error="",
    )


def mark_failed(task_id: str, error: str, message: str | None = None) -> dict[str, Any]:
    return task_repository.update_task_status(
        task_id,
        TaskStatus.FAILED.value,
        message=message,
        error=error,
    )


def get_task(task_id: str) -> dict[str, Any] | None:
    return task_repository.get_task(task_id)


def list_tasks(limit: int = 100, *, view: str = "recent", status: str | None = None) -> list[dict[str, Any]]:
    cleanup_stale_tasks()
    return task_repository.list_tasks(limit=limit, view=view, status=status)


def archive_terminal_tasks() -> int:
    return task_repository.archive_terminal_tasks()
