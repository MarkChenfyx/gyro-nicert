from __future__ import annotations

from typing import Any

from backend.domain.enums import TaskStatus
from backend.repositories import task_repository


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


def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    return task_repository.list_tasks(limit=limit)
