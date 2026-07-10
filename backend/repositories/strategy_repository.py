from __future__ import annotations

from typing import Any

from common.time_utils import now_iso
from data_manager.database import get_app_db_connection


def _now() -> str:
    return now_iso()


def create_strategy(
    strategy_id: str,
    strategy_name: str,
    strategy_family: str,
    strategy_version: str,
    source_filename: str,
    source_type: str,
    source_text: str | None,
    class_name: str | None,
    code_path: str,
    code_hash: str | None = None,
) -> dict[str, Any]:
    created_at = _now()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO strategies (
                strategy_id, strategy_name, strategy_family, strategy_version, source_filename,
                source_type, source_text, class_name, code_path, code_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(strategy_id),
                str(strategy_name),
                str(strategy_family),
                str(strategy_version),
                str(source_filename),
                str(source_type),
                source_text,
                class_name,
                str(code_path),
                code_hash,
                created_at,
            ),
        )
        connection.commit()
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise RuntimeError(f"Strategy was not created: {strategy_id}")
    return strategy


def get_strategy(strategy_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM strategies WHERE strategy_id = ?",
            (str(strategy_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def list_strategies(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 100), 1000))
    with get_app_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM strategies ORDER BY created_at DESC, strategy_id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]
