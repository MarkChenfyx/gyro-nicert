from __future__ import annotations

from typing import Any
import json

from backend.common.time_utils import now_iso
from backend.data_manager.database import get_app_db_connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS live_sources (
    source_id TEXT PRIMARY KEY, name TEXT NOT NULL, source_kind TEXT NOT NULL,
    package_path TEXT NOT NULL, package_hash TEXT NOT NULL,
    first_date TEXT NOT NULL, instance_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_bindings (
    binding_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
    instance_name TEXT NOT NULL, class_name TEXT NOT NULL, module_path TEXT NOT NULL,
    vt_symbol TEXT NOT NULL, fixed_size REAL NOT NULL,
    parameters_json TEXT NOT NULL, config_hash TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(source_id, instance_name)
);
CREATE TABLE IF NOT EXISTS live_snapshots (
    snapshot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, trade_date TEXT NOT NULL,
    setting_hash TEXT NOT NULL, state_hash TEXT NOT NULL, artifact_path TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(source_id, trade_date)
);
CREATE TABLE IF NOT EXISTS live_daily_records (
    record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, trade_date TEXT NOT NULL,
    summary_json TEXT NOT NULL, artifact_path TEXT NOT NULL, error TEXT,
    created_at TEXT NOT NULL, UNIQUE(source_id, trade_date)
);
"""

def _connect():
    connection = get_app_db_connection()
    connection.executescript(SCHEMA)
    return connection


def _decode(row: Any, *fields: str) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for field in fields:
        item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
    return item


def create_source(source: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO live_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source["source_id"], source["name"], source["source_kind"],
                source["package_path"], source["package_hash"],
                source["first_date"], source["instance_count"], now_iso(),
            ),
        )
        connection.commit()
    return get_source(str(source["source_id"])) or {}


def get_source(source_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM live_sources WHERE source_id = ?", (source_id,)).fetchone()
    return dict(row) if row is not None else None


def list_sources() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM live_sources ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def create_bindings(rows: list[dict[str, Any]]) -> None:
    created_at = now_iso()
    with _connect() as connection:
        connection.executemany(
            """
            INSERT INTO live_bindings (
                binding_id, source_id, instance_name, class_name, module_path,
                vt_symbol, fixed_size, parameters_json, config_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["binding_id"], row["source_id"], row["instance_name"], row["class_name"],
                    row["module_path"], row["vt_symbol"], row["fixed_size"],
                    json.dumps(row["parameters"], ensure_ascii=False, sort_keys=True),
                    row["config_hash"], created_at,
                )
                for row in rows
            ],
        )
        connection.commit()


def list_bindings(source_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM live_bindings WHERE source_id = ? ORDER BY instance_name", (source_id,)
        ).fetchall()
    return [_decode(row, "parameters_json") or {} for row in rows]


def create_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO live_snapshots (
                snapshot_id, source_id, trade_date, setting_hash, state_hash, artifact_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot["snapshot_id"], snapshot["source_id"], snapshot["trade_date"],
                snapshot["setting_hash"], snapshot["state_hash"], snapshot["artifact_path"], now_iso(),
            ),
        )
        connection.commit()
    return get_snapshot_for_date(str(snapshot["source_id"]), str(snapshot["trade_date"])) or {}


def get_snapshot_for_date(source_id: str, trade_date: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM live_snapshots WHERE source_id = ? AND trade_date = ?", (source_id, trade_date)
        ).fetchone()
    return dict(row) if row is not None else None


def find_snapshot_by_state_hash(state_hash: str) -> dict[str, Any] | None:
    """这份状态内容是否已经被记录成某天的快照。"""
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM live_snapshots WHERE state_hash = ? ORDER BY trade_date DESC LIMIT 1",
            (state_hash,),
        ).fetchone()
    return dict(row) if row is not None else None


def previous_snapshot(source_id: str, trade_date: str) -> dict[str, Any] | None:
    """取该日之前最近的一份快照，作为单日回放的起点。"""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM live_snapshots WHERE source_id = ? AND trade_date < ?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (source_id, trade_date),
        ).fetchone()
    return dict(row) if row is not None else None


def list_snapshots(source_id: str, limit: int = 60) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM live_snapshots WHERE source_id = ? ORDER BY trade_date DESC LIMIT ?",
            (source_id, max(1, min(int(limit), 365))),
        ).fetchall()
    return [dict(row) for row in rows]


def save_daily_record(record: dict[str, Any]) -> dict[str, Any]:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO live_daily_records (
                record_id, source_id, trade_date, summary_json, artifact_path, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, trade_date) DO UPDATE SET
                record_id = excluded.record_id,
                summary_json = excluded.summary_json,
                artifact_path = excluded.artifact_path,
                error = excluded.error,
                created_at = excluded.created_at
            """,
            (
                record["record_id"], record["source_id"], record["trade_date"],
                json.dumps(record.get("summary") or {}, ensure_ascii=False),
                record["artifact_path"], record.get("error"), now_iso(),
            ),
        )
        connection.commit()
    return get_daily_record(str(record["source_id"]), str(record["trade_date"])) or {}


def get_daily_record(source_id: str, trade_date: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM live_daily_records WHERE source_id = ? AND trade_date = ?",
            (source_id, trade_date),
        ).fetchone()
    return _decode(row, "summary_json")


def list_daily_records(source_id: str, limit: int = 60) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM live_daily_records WHERE source_id = ? ORDER BY trade_date DESC LIMIT ?",
            (source_id, max(1, min(int(limit), 365))),
        ).fetchall()
    return [_decode(row, "summary_json") or {} for row in rows]


def delete_source(source_id: str) -> None:
    """导入失败时回滚，只清除本次导入写入的行。"""
    with _connect() as connection:
        for table in ("live_daily_records", "live_snapshots", "live_bindings", "live_sources"):
            connection.execute(f"DELETE FROM {table} WHERE source_id = ?", (source_id,))
        connection.commit()
