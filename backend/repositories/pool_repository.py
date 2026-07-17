from __future__ import annotations

from typing import Any
import json

from backend.common.time_utils import now_iso, timestamp_id
from backend.data_manager.database import get_app_db_connection


ALLOWED_SORT_FIELDS = {
    "created_at": "created_at",
    "annual_return": "annual_return",
    "max_drawdown": "max_drawdown",
    "sharpe": "sharpe",
    "calmar": "calmar",
}


def _now() -> str:
    return now_iso()


def _pool_item_id() -> str:
    return f"pool_{timestamp_id()}"


def create_pool_item(
    pool_item_id: str | None,
    strategy_id: str,
    source_run_id: str,
    source_variant_id: str,
    pool_path: str,
    strategy_name: str,
    strategy_family: str | None = None,
    strategy_version: str | None = None,
    vt_symbol: str | None = None,
    annual_return: float | None = None,
    max_drawdown: float | None = None,
    sharpe: float | None = None,
    calmar: float | None = None,
    tags: list[str] | str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    resolved_pool_item_id = pool_item_id or _pool_item_id()
    tags_text = tags if isinstance(tags, str) else json.dumps(list(tags or []), ensure_ascii=False)
    resolved_created_at = str(created_at or _now())
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO pool_items (
                pool_item_id, strategy_id, source_run_id, source_variant_id, pool_path,
                strategy_name, strategy_family, strategy_version, vt_symbol,
                annual_return, max_drawdown, sharpe, calmar, tags, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_pool_item_id,
                str(strategy_id),
                str(source_run_id),
                str(source_variant_id),
                str(pool_path),
                str(strategy_name),
                strategy_family,
                strategy_version,
                vt_symbol,
                annual_return,
                max_drawdown,
                sharpe,
                calmar,
                tags_text,
                resolved_created_at,
            ),
        )
        connection.commit()
    item = get_pool_item(resolved_pool_item_id)
    if item is None:
        raise RuntimeError(f"Pool item was not created: {resolved_pool_item_id}")
    return item


def get_pool_item(pool_item_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM pool_items WHERE pool_item_id = ?",
            (str(pool_item_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def update_pool_item_metrics(
    pool_item_id: str,
    *,
    annual_return: float | None,
    max_drawdown: float | None,
    sharpe: float | None,
    calmar: float | None,
) -> dict[str, Any]:
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE pool_items
            SET annual_return = ?, max_drawdown = ?, sharpe = ?, calmar = ?
            WHERE pool_item_id = ?
            """,
            (annual_return, max_drawdown, sharpe, calmar, str(pool_item_id)),
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Pool item not found: {pool_item_id}")
    item = get_pool_item(pool_item_id)
    if item is None:
        raise KeyError(f"Pool item not found: {pool_item_id}")
    return item


def list_pool_items(
    keyword: str | None = None,
    vt_symbol: str | None = None,
    min_sharpe: float | None = None,
    tag: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if keyword:
        clauses.append("strategy_name LIKE ?")
        values.append(f"%{keyword}%")
    if vt_symbol:
        clauses.append("vt_symbol = ?")
        values.append(str(vt_symbol))
    if min_sharpe is not None:
        clauses.append("sharpe >= ?")
        values.append(float(min_sharpe))
    if tag:
        clauses.append("tags LIKE ?")
        values.append(f"%{tag}%")

    sort_column = ALLOWED_SORT_FIELDS.get(str(sort_by or "created_at"), "created_at")
    sort_order = "ASC" if str(order or "desc").lower() == "asc" else "DESC"
    safe_limit = max(1, min(int(limit or 100), 1000))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM pool_items
        {where_sql}
        ORDER BY {sort_column} {sort_order}, pool_item_id {sort_order}
        LIMIT ?
    """
    values.append(safe_limit)

    with get_app_db_connection() as connection:
        rows = connection.execute(sql, tuple(values)).fetchall()
    return [dict(row) for row in rows]


def delete_pool_item(pool_item_id: str) -> bool:
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM pool_items WHERE pool_item_id = ?",
            (str(pool_item_id),),
        )
        connection.commit()
    return cursor.rowcount > 0
