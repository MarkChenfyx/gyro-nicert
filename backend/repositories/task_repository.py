from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.common.time_utils import now_iso
from backend.domain.enums import TaskStatus
from backend.data_manager.database import get_app_db_connection


def _now() -> str:
    return now_iso()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


TERMINAL_STATUSES = (
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
)


def _ensure_archived_column(connection: Any) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
    if "archived_at" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN archived_at TEXT")
        connection.commit()


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
        _ensure_archived_column(connection)
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
        _ensure_archived_column(connection)
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
        _ensure_archived_column(connection)
        row = connection.execute(
            """
            SELECT tasks.*, strategies.source_filename AS source_filename
            FROM tasks
            LEFT JOIN strategies ON strategies.strategy_id = tasks.related_strategy_id
            WHERE tasks.task_id = ?
            """,
            (task_id,),
        ).fetchone()
    return _row_to_dict(row)


def list_tasks(limit: int = 100, *, view: str = "recent", status: str | None = None) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 1000))
    clauses: list[str] = []
    values: list[Any] = []
    if view == "active":
        clauses.extend(["archived_at IS NULL", "status IN (?, ?)"])
        values.extend([TaskStatus.RUNNING.value, TaskStatus.QUEUED.value])
    elif view == "recent":
        clauses.append("archived_at IS NULL")
    elif view == "archived":
        clauses.append("archived_at IS NOT NULL")
    elif view != "all":
        raise ValueError(f"Unsupported task view: {view}")
    if status:
        clauses.append("status = ?")
        values.append(str(status))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(safe_limit)
    with get_app_db_connection() as connection:
        _ensure_archived_column(connection)
        qualified_where = where.replace("archived_at", "tasks.archived_at").replace("status", "tasks.status")
        rows = connection.execute(
            f"""
            SELECT tasks.*, strategies.source_filename AS source_filename
            FROM tasks
            LEFT JOIN strategies ON strategies.strategy_id = tasks.related_strategy_id
            {qualified_where}
            ORDER BY tasks.created_at DESC, tasks.task_id DESC LIMIT ?
            """,
            tuple(values),
        ).fetchall()
    return [dict(row) for row in rows]


def archive_terminal_tasks() -> int:
    archived_at = _now()
    with get_app_db_connection() as connection:
        _ensure_archived_column(connection)
        cursor = connection.execute(
            """
            UPDATE tasks
            SET archived_at = ?, updated_at = ?
            WHERE archived_at IS NULL AND status IN (?, ?, ?)
            """,
            (archived_at, archived_at, *TERMINAL_STATUSES),
        )
        connection.commit()
        return int(cursor.rowcount)
