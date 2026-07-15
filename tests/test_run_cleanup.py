from __future__ import annotations

import sqlite3

import pytest

from backend.repositories import run_repository
from backend.services import run_cleanup_service, run_service


SCHEMA = """
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    task_id TEXT,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE run_variants (
    variant_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    variant_name TEXT NOT NULL
);
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL
);
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    related_run_id TEXT
);
CREATE TABLE pool_items (
    pool_item_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    source_variant_id TEXT NOT NULL,
    pool_path TEXT NOT NULL
);
"""


def _connection_factory(path):
    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    return connect


def _prepare(tmp_path, monkeypatch):
    db_path = tmp_path / "app.sqlite"
    runs_root = tmp_path / "storage" / "runtime" / "runs"
    pool_root = tmp_path / "storage" / "pool" / "strategies"
    runs_root.mkdir(parents=True)
    pool_root.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA)
    factory = _connection_factory(db_path)
    monkeypatch.setattr(run_repository, "get_app_db_connection", factory)
    monkeypatch.setattr(run_cleanup_service, "get_app_db_connection", factory)
    return db_path, runs_root, pool_root


def _insert_run(db_path, runs_root, run_id, *, status="completed", created_at="2026-01-01"):
    run_path = runs_root / run_id
    run_path.mkdir()
    (run_path / "result.json").write_text("{}", encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, "strategy_1", f"task_{run_id}", "baseline", status, str(run_path), created_at, created_at),
        )
        connection.execute("INSERT INTO run_variants VALUES (?, ?, ?)", (f"variant_{run_id}", run_id, "baseline"))
        connection.execute("INSERT INTO artifacts VALUES (?, ?, ?)", (f"artifact_run_{run_id}", "run", run_id))
        connection.execute("INSERT INTO artifacts VALUES (?, ?, ?)", (f"artifact_variant_{run_id}", "variant", f"variant_{run_id}"))
        connection.execute("INSERT INTO tasks VALUES (?, ?)", (f"task_{run_id}", run_id))
    return run_path


def test_delete_run_removes_runtime_indexes_but_preserves_pool_snapshot(tmp_path, monkeypatch):
    db_path, runs_root, pool_root = _prepare(tmp_path, monkeypatch)
    run_path = _insert_run(db_path, runs_root, "run_old")
    pool_path = pool_root / "pool_1"
    pool_path.mkdir()
    (pool_path / "manifest.json").write_text("{}", encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO pool_items VALUES (?, ?, ?, ?)",
            ("pool_1", "run_old", "variant_run_old", str(pool_path)),
        )

    result = run_cleanup_service.delete_run("run_old", runs_root=runs_root)

    assert result == {"run_id": "run_old", "variant_count": 1, "directory_removed": True}
    assert not run_path.exists()
    assert pool_path.is_dir()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM run_variants").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
        assert connection.execute("SELECT related_run_id FROM tasks").fetchone()[0] is None
        assert connection.execute("SELECT source_run_id FROM pool_items").fetchone()[0] == "run_old"


def test_delete_run_rejects_non_terminal_and_outside_paths(tmp_path, monkeypatch):
    db_path, runs_root, _ = _prepare(tmp_path, monkeypatch)
    _insert_run(db_path, runs_root, "run_running", status="running")
    with pytest.raises(ValueError, match="not terminal"):
        run_cleanup_service.delete_run("run_running", runs_root=runs_root)

    outside = tmp_path / "outside"
    outside.mkdir()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_outside", "strategy_1", None, "baseline", "completed", str(outside), "2026-01-01", "2026-01-01"),
        )
    with pytest.raises(ValueError, match="outside runtime root"):
        run_cleanup_service.delete_run("run_outside", runs_root=runs_root)
    assert outside.is_dir()


def test_prune_keeps_newest_and_audit_only_reports_orphans(tmp_path, monkeypatch):
    db_path, runs_root, _ = _prepare(tmp_path, monkeypatch)
    _insert_run(db_path, runs_root, "run_old", created_at="2026-01-01")
    _insert_run(db_path, runs_root, "run_new", created_at="2026-01-02")
    (runs_root / "directory_only").mkdir()
    missing_path = runs_root / "database_only"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("database_only", "strategy_1", None, "baseline", "completed", str(missing_path), "2026-01-03", "2026-01-03"),
        )

    audit = run_cleanup_service.audit_orphans(runs_root=runs_root)

    assert audit["database_without_directory"] == ["database_only"]
    assert audit["directory_without_database"] == ["directory_only"]
    assert (runs_root / "directory_only").is_dir()

    result = run_cleanup_service.prune_runs(retention=2, runs_root=runs_root)
    assert result["deleted_run_ids"] == ["run_old"]
    assert (runs_root / "run_new").is_dir()
    assert (runs_root / "directory_only").is_dir()


def test_baseline_retention_is_best_effort(monkeypatch, caplog):
    def fail_prune():
        raise OSError("temporary cleanup failure")

    monkeypatch.setattr(run_cleanup_service, "prune_runs", fail_prune)

    run_service._prune_runs_best_effort("run_new")

    assert "temporary cleanup failure" in caplog.text
