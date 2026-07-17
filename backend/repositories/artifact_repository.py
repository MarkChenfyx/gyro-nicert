from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.common.time_utils import now_iso
from backend.data_manager.database import get_app_db_connection


def _now() -> str:
    return now_iso()


def create_artifact(
    owner_type: str,
    owner_id: str,
    artifact_type: str,
    path: str | Path,
    *,
    artifact_id: str | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    resolved_artifact_id = artifact_id or f"artifact_{uuid4().hex[:12]}"
    created_at = _now()
    with get_app_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, owner_type, owner_id, artifact_type, path, sha256, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_artifact_id,
                str(owner_type),
                str(owner_id),
                str(artifact_type),
                str(path),
                sha256,
                created_at,
            ),
        )
        connection.commit()
    artifact = get_artifact(resolved_artifact_id)
    if artifact is None:
        raise RuntimeError(f"Artifact was not created: {resolved_artifact_id}")
    return artifact


def list_artifacts(owner_type: str, owner_id: str) -> list[dict[str, Any]]:
    with get_app_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM artifacts
            WHERE owner_type = ? AND owner_id = ?
            ORDER BY created_at ASC, artifact_id ASC
            """,
            (str(owner_type), str(owner_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    with get_app_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_artifacts_by_owner(owner_type: str, owner_id: str) -> int:
    with get_app_db_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM artifacts WHERE owner_type = ? AND owner_id = ?",
            (str(owner_type), str(owner_id)),
        )
        connection.commit()
    return cursor.rowcount
