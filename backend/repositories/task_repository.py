from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.domain.enums import TaskStatus
from data_manager.database import get_app_db_connection


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_task(
    task_type: str,
    *,
    task_id: str | None = None,
    status: str = TaskStatus.QUEUED.value,
    progress: float = 0.0,
    message: str | None = None,
    error: str | None = None,
    related_strategy_id: str | None = None,
    related_run_id: str | None = None,
    related_pool_item_id: str | None = None,
) -> dict[str, Any]:
    resolved_task_id = task_id or f"task_{uuid4().hex[:12]}"
    created_at = _now()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, task_type, status, progress, message, error,
                related_strategy_id, related_run_id, related_pool_item_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_task_id,
                str(task_type),
                str(status),
                float(progress),
                message,
                error,
                related_strategy_id,
                related_run_id,
                related_pool_item_id,
                created_at,
                created_at,
            ),
        )
        connection.commit()
    task = get_task(resolved_task_id)
    if task is None:
        raise RuntimeError(f"Task was not created: {resolved_task_id}")
    return task


def update_task_status(
    task_id: str,
    status: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    updates = ["status = ?", "updated_at = ?"]
    values: list[Any] = [str(status), _now()]
    if progress is not None:
        updates.append("progress = ?")
        values.append(float(progress))
    if message is not None:
        updates.append("message = ?")
        values.append(message)
    if error is not None:
        updates.append("error = ?")
        values.append(error)
    values.append(task_id)

    with get_app_db_connection() as connection:
        cursor = connection.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
            tuple(values),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Task not found: {task_id}")
    task = get_task(task_id)
    if task is None:
        raise KeyError(f"Task not found: {task_id}")
    return task


def get_task(task_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return _row_to_dict(row)


def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 1000))
    with get_app_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, task_id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]

