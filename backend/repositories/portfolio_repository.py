from __future__ import annotations

from typing import Any
import json

from backend.core.paths import stored_path, path_fields
from backend.common.time_utils import now_iso
from backend.data_manager.database import get_app_db_connection


def _components(connection: Any, portfolio_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT portfolio_id, pool_item_id, weight, sort_order, created_at
        FROM virtual_portfolio_components
        WHERE portfolio_id = ?
        ORDER BY sort_order ASC, pool_item_id ASC
        """,
        (str(portfolio_id),),
    ).fetchall()
    return [path_fields(dict(row)) for row in rows]


def create_portfolio(
    *,
    portfolio_id: str,
    name: str,
    description: str,
    virtual_capital: float,
    start_date: str,
    end_date: str,
    alignment_mode: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    created_at = now_iso()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO virtual_portfolios (
                portfolio_id, name, description, virtual_capital, start_date, end_date,
                alignment_mode, latest_snapshot_id, archived_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                portfolio_id,
                name,
                description,
                virtual_capital,
                start_date,
                end_date,
                alignment_mode,
                created_at,
                created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO virtual_portfolio_components (
                portfolio_id, pool_item_id, weight, sort_order, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    portfolio_id,
                    str(item["pool_item_id"]),
                    float(item["weight"]),
                    index,
                    created_at,
                )
                for index, item in enumerate(components)
            ],
        )
        connection.commit()
    portfolio = get_portfolio(portfolio_id)
    if portfolio is None:
        raise RuntimeError(f"组合创建失败：{portfolio_id}")
    return portfolio


def update_portfolio(
    portfolio_id: str,
    *,
    name: str,
    description: str,
    virtual_capital: float,
    start_date: str,
    end_date: str,
    alignment_mode: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    updated_at = now_iso()
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE virtual_portfolios
            SET name = ?, description = ?, virtual_capital = ?, start_date = ?, end_date = ?,
                alignment_mode = ?, updated_at = ?
            WHERE portfolio_id = ? AND archived_at IS NULL
            """,
            (name, description, virtual_capital, start_date, end_date, alignment_mode, updated_at, portfolio_id),
        )
        if cursor.rowcount == 0:
            raise FileNotFoundError(f"组合不存在或已归档：{portfolio_id}")
        connection.execute("DELETE FROM virtual_portfolio_components WHERE portfolio_id = ?", (portfolio_id,))
        connection.executemany(
            """
            INSERT INTO virtual_portfolio_components (
                portfolio_id, pool_item_id, weight, sort_order, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (portfolio_id, str(item["pool_item_id"]), float(item["weight"]), index, updated_at)
                for index, item in enumerate(components)
            ],
        )
        connection.commit()
    portfolio = get_portfolio(portfolio_id)
    if portfolio is None:
        raise FileNotFoundError(f"组合不存在：{portfolio_id}")
    return portfolio


def get_portfolio(portfolio_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM virtual_portfolios WHERE portfolio_id = ?",
            (str(portfolio_id),),
        ).fetchone()
        if row is None:
            return None
        item = path_fields(dict(row))
        item["components"] = _components(connection, portfolio_id)
    return item


def list_portfolios(*, include_archived: bool = False) -> list[dict[str, Any]]:
    where_sql = "" if include_archived else "WHERE p.archived_at IS NULL"
    with get_app_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT p.*, COUNT(c.pool_item_id) AS component_count
            FROM virtual_portfolios p
            LEFT JOIN virtual_portfolio_components c ON c.portfolio_id = p.portfolio_id
            {where_sql}
            GROUP BY p.portfolio_id
            ORDER BY p.updated_at DESC, p.portfolio_id DESC
            """
        ).fetchall()
    return [path_fields(dict(row)) for row in rows]


def create_snapshot(
    *,
    snapshot_id: str,
    portfolio_id: str,
    definition_hash: str,
    source_hashes: dict[str, str],
    metrics: dict[str, Any],
    artifact_path: str,
) -> dict[str, Any]:
    created_at = now_iso()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO virtual_portfolio_snapshots (
                snapshot_id, portfolio_id, definition_hash, source_hashes, metrics, artifact_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                portfolio_id,
                definition_hash,
                json.dumps(source_hashes, ensure_ascii=False, sort_keys=True),
                json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                stored_path(artifact_path),
                created_at,
            ),
        )
        connection.execute(
            "UPDATE virtual_portfolios SET latest_snapshot_id = ?, updated_at = ? WHERE portfolio_id = ?",
            (snapshot_id, created_at, portfolio_id),
        )
        connection.commit()
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        raise RuntimeError(f"组合快照创建失败：{snapshot_id}")
    return snapshot


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM virtual_portfolio_snapshots WHERE snapshot_id = ?",
            (str(snapshot_id),),
        ).fetchone()
    if row is None:
        return None
    item = path_fields(dict(row))
    item["source_hashes"] = json.loads(item.get("source_hashes") or "{}")
    item["metrics"] = json.loads(item.get("metrics") or "{}")
    return item


def get_latest_snapshot(portfolio_id: str) -> dict[str, Any] | None:
    portfolio = get_portfolio(portfolio_id)
    snapshot_id = str((portfolio or {}).get("latest_snapshot_id") or "")
    return get_snapshot(snapshot_id) if snapshot_id else None


def archive_portfolio(portfolio_id: str) -> dict[str, Any]:
    archived_at = now_iso()
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            "UPDATE virtual_portfolios SET archived_at = ?, updated_at = ? WHERE portfolio_id = ? AND archived_at IS NULL",
            (archived_at, archived_at, str(portfolio_id)),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise FileNotFoundError(f"组合不存在或已归档：{portfolio_id}")
    item = get_portfolio(portfolio_id)
    if item is None:
        raise FileNotFoundError(f"组合不存在：{portfolio_id}")
    return item
