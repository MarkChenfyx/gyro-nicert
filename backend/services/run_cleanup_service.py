from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.core.paths import RUNS_ROOT
from backend.repositories import run_repository
from backend.data_manager.database import get_app_db_connection


LOGGER = logging.getLogger(__name__)
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
DEFAULT_RUN_RETENTION = 50


def configured_retention() -> int:
    raw_value = os.getenv("GYRO_RUN_RETENTION", str(DEFAULT_RUN_RETENTION))
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        LOGGER.warning("Invalid GYRO_RUN_RETENTION=%r; using %s", raw_value, DEFAULT_RUN_RETENTION)
        return DEFAULT_RUN_RETENTION


def _validated_run_path(run: dict[str, Any], runs_root: str | Path) -> tuple[Path, Path]:
    root = Path(runs_root).resolve()
    candidate = Path(str(run.get("runtime_path") or "")).resolve()
    expected = (root / str(run["run_id"])).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Refusing to delete run path outside runtime root: {candidate}") from exc
    if candidate == root or candidate != expected:
        raise ValueError(f"Refusing to delete unexpected run path: {candidate}")
    return root, candidate


def delete_run(run_id: str, *, runs_root: str | Path = RUNS_ROOT) -> dict[str, Any]:
    """Delete one terminal runtime run while leaving pool snapshots untouched."""
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    status = str(run.get("status") or "").lower()
    if status not in TERMINAL_RUN_STATUSES:
        raise ValueError(f"Run is not terminal and cannot be deleted: {run_id} ({status})")

    root, run_path = _validated_run_path(run, runs_root)
    if run_path.exists() and not run_path.is_dir():
        raise ValueError(f"Run path is not a directory: {run_path}")

    staged_path: Path | None = None
    if run_path.exists():
        staged_path = root / f".{run_id}.deleting-{uuid4().hex[:8]}"
        run_path.rename(staged_path)

    try:
        with get_app_db_connection() as connection:
            variant_rows = connection.execute(
                "SELECT variant_id FROM run_variants WHERE run_id = ?",
                (str(run_id),),
            ).fetchall()
            variant_ids = [str(row[0]) for row in variant_rows]
            if variant_ids:
                placeholders = ",".join("?" for _ in variant_ids)
                connection.execute(
                    f"DELETE FROM artifacts WHERE owner_type = 'variant' AND owner_id IN ({placeholders})",
                    tuple(variant_ids),
                )
            connection.execute(
                "DELETE FROM artifacts WHERE owner_type = 'run' AND owner_id = ?",
                (str(run_id),),
            )
            connection.execute(
                "UPDATE tasks SET related_run_id = NULL WHERE related_run_id = ?",
                (str(run_id),),
            )
            connection.execute("DELETE FROM run_variants WHERE run_id = ?", (str(run_id),))
            cursor = connection.execute("DELETE FROM runs WHERE run_id = ?", (str(run_id),))
            if cursor.rowcount != 1:
                raise RuntimeError(f"Run disappeared during cleanup: {run_id}")
            connection.commit()
    except Exception:
        if staged_path is not None and staged_path.exists() and not run_path.exists():
            staged_path.rename(run_path)
        raise

    directory_removed = staged_path is not None
    if staged_path is not None:
        shutil.rmtree(staged_path)
    return {
        "run_id": str(run_id),
        "variant_count": len(variant_ids),
        "directory_removed": directory_removed,
    }


def prune_runs(*, retention: int | None = None, runs_root: str | Path = RUNS_ROOT) -> dict[str, Any]:
    keep_count = max(1, int(retention if retention is not None else configured_retention()))
    runs = run_repository.list_runs(limit=1000)
    candidates = [
        run for run in runs[keep_count:]
        if str(run.get("status") or "").lower() in TERMINAL_RUN_STATUSES
    ]
    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    for run in candidates:
        run_id = str(run["run_id"])
        try:
            delete_run(run_id, runs_root=runs_root)
            deleted.append(run_id)
        except Exception as exc:  # best-effort cleanup must continue with other candidates
            LOGGER.exception("Failed to prune run %s", run_id)
            errors.append({"run_id": run_id, "error": str(exc)})
    return {"retention": keep_count, "deleted_run_ids": deleted, "errors": errors}


def audit_orphans(*, runs_root: str | Path = RUNS_ROOT) -> dict[str, list[str]]:
    root = Path(runs_root).resolve()
    database_runs = run_repository.list_runs(limit=1000)
    database_ids = {str(run["run_id"]) for run in database_runs}
    database_without_directory: list[str] = []
    unsafe_runtime_paths: list[str] = []
    for run in database_runs:
        run_id = str(run["run_id"])
        try:
            _, run_path = _validated_run_path(run, root)
        except ValueError:
            unsafe_runtime_paths.append(run_id)
            continue
        if not run_path.is_dir():
            database_without_directory.append(run_id)

    directory_ids = {
        child.name
        for child in root.iterdir()
        if child.is_dir()
    } if root.exists() else set()
    return {
        "database_without_directory": sorted(database_without_directory),
        "directory_without_database": sorted(directory_ids - database_ids),
        "unsafe_runtime_paths": sorted(unsafe_runtime_paths),
    }
