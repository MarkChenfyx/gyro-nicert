from __future__ import annotations

from typing import Any

from common.time_utils import now_iso
from data_manager.database import get_app_db_connection


def _now() -> str:
    return now_iso()


def create_run(
    run_id: str,
    strategy_id: str,
    task_id: str | None,
    run_type: str,
    status: str,
    runtime_path: str,
) -> dict[str, Any]:
    created_at = _now()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id, strategy_id, task_id, run_type, status, runtime_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                str(strategy_id),
                task_id,
                str(run_type),
                str(status),
                str(runtime_path),
                created_at,
                created_at,
            ),
        )
        connection.commit()
    run = get_run(run_id)
    if run is None:
        raise RuntimeError(f"Run was not created: {run_id}")
    return run


def update_run_status(run_id: str, status: str) -> dict[str, Any]:
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (str(status), _now(), str(run_id)),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Run not found: {run_id}")
    run = get_run(run_id)
    if run is None:
        raise KeyError(f"Run not found: {run_id}")
    return run


def get_run(run_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 1000))
    with get_app_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]
