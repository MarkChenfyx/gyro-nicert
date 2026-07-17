from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.common.time_utils import now_iso, timestamp_id
from backend.data_manager.database import get_app_db_connection


def _now() -> str:
    return now_iso()


def _variant_id() -> str:
    return f"variant_{timestamp_id()}_{uuid4().hex[:6]}"


def create_variant(
    variant_id: str | None,
    run_id: str,
    variant_name: str,
    params_hash: str | None,
    config_path: str | None,
    result_path: str,
    daily_results_path: str | None = None,
    trades_path: str | None = None,
) -> dict[str, Any]:
    resolved_variant_id = variant_id or _variant_id()
    created_at = _now()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO run_variants (
                variant_id, run_id, variant_name, params_hash, config_path, result_path,
                daily_results_path, trades_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_variant_id,
                str(run_id),
                str(variant_name),
                params_hash,
                config_path,
                str(result_path),
                daily_results_path,
                trades_path,
                created_at,
            ),
        )
        connection.commit()
    variant = get_variant(resolved_variant_id)
    if variant is None:
        raise RuntimeError(f"Variant was not created: {resolved_variant_id}")
    return variant


def get_variant(variant_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM run_variants WHERE variant_id = ?",
            (str(variant_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def get_variant_by_run_and_name(run_id: str, variant_name: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM run_variants
            WHERE run_id = ? AND variant_name = ?
            ORDER BY created_at DESC, variant_id DESC
            LIMIT 1
            """,
            (str(run_id), str(variant_name)),
        ).fetchone()
    return dict(row) if row is not None else None


def list_variants(run_id: str) -> list[dict[str, Any]]:
    with get_app_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM run_variants
            WHERE run_id = ?
            ORDER BY created_at ASC, variant_id ASC
            """,
            (str(run_id),),
        ).fetchall()
    return [dict(row) for row in rows]
