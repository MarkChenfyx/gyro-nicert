from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.main import app
from backend.repositories import task_repository
from backend.services import task_service


OLD_TASK_SCHEMA = """
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    message TEXT,
    error TEXT,
    related_strategy_id TEXT,
    related_run_id TEXT,
    related_pool_item_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _connection_factory(path):
    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    return connect


def test_task_repository_migrates_filters_and_archives(tmp_path, monkeypatch):
    db_path = tmp_path / "app.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(OLD_TASK_SCHEMA)
        connection.execute("CREATE TABLE strategies (strategy_id TEXT PRIMARY KEY, source_filename TEXT)")
    monkeypatch.setattr(task_repository, "get_app_db_connection", _connection_factory(db_path))

    running = task_repository.create_task("backtest", task_id="task_running", status="running")
    completed = task_repository.create_task("optimization", task_id="task_completed", status="completed")
    failed = task_repository.create_task("data_download", task_id="task_failed", status="failed")

    assert running["archived_at"] is None
    assert {row["task_id"] for row in task_repository.list_tasks(view="active")} == {"task_running"}
    assert {row["task_id"] for row in task_repository.list_tasks(view="recent")} == {
        "task_running",
        "task_completed",
        "task_failed",
    }

    assert task_repository.archive_terminal_tasks() == 2
    assert {row["task_id"] for row in task_repository.list_tasks(view="recent")} == {"task_running"}
    assert {row["task_id"] for row in task_repository.list_tasks(view="archived")} == {
        "task_completed",
        "task_failed",
    }


def test_task_api_exposes_views_and_terminal_archive(tmp_path, monkeypatch):
    db_path = tmp_path / "app.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(OLD_TASK_SCHEMA)
        connection.execute("CREATE TABLE strategies (strategy_id TEXT PRIMARY KEY, source_filename TEXT)")
    monkeypatch.setattr(task_repository, "get_app_db_connection", _connection_factory(db_path))
    task_repository.create_task("backtest", task_id="task_running", status="running")
    task_repository.create_task("optimization", task_id="task_completed", status="completed")

    client = TestClient(app)
    active = client.get("/api/tasks", params={"view": "active"})
    assert active.status_code == 200
    assert [row["task_id"] for row in active.json()["tasks"]] == ["task_running"]

    archived = client.post("/api/tasks/archive", json={"scope": "terminal"})
    assert archived.status_code == 200
    assert archived.json() == {"archived_count": 1}
    assert client.get("/api/tasks", params={"view": "archived"}).json()["tasks"][0]["task_id"] == "task_completed"


def test_task_repository_reclaims_stale_active_tasks(tmp_path, monkeypatch):
    db_path = tmp_path / "app.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(OLD_TASK_SCHEMA)
        connection.execute("CREATE TABLE strategies (strategy_id TEXT PRIMARY KEY, source_filename TEXT)")
    monkeypatch.setattr(task_repository, "get_app_db_connection", _connection_factory(db_path))

    task_repository.create_task("strategy_research", task_id="task_stale", status="running")
    task_repository.create_task("backtest", task_id="task_fresh", status="running")
    task_repository.create_task("optimization", task_id="task_done", status="completed")
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", ("2026-07-20T08:00:00+08:00", "task_stale"))
        connection.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", ("2026-07-23T11:30:00+08:00", "task_fresh"))

    reclaimed = task_repository.reclaim_stale_tasks("2026-07-23T06:00:00+08:00", stale_hours=6)

    assert reclaimed == 1
    stale = task_repository.get_task("task_stale")
    assert stale is not None
    assert stale["status"] == "cancelled"
    assert stale["archived_at"] is not None
    assert "连续 6 小时没有更新" in stale["error"]
    assert task_repository.get_task("task_fresh")["status"] == "running"
    assert task_repository.get_task("task_done")["archived_at"] is None
    assert {row["task_id"] for row in task_repository.list_tasks(view="active")} == {"task_fresh"}

    resumed = task_repository.update_task_status("task_stale", "running", progress=0.75, message="任务恢复")
    assert resumed["archived_at"] is None
    assert resumed["status"] == "running"


def test_task_service_scans_for_stale_tasks_before_listing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(task_service, "cleanup_stale_tasks", lambda: calls.append("cleanup") or 0)
    monkeypatch.setattr(task_service.task_repository, "list_tasks", lambda **_kwargs: [])

    assert task_service.list_tasks(limit=5, view="recent") == []
    assert calls == ["cleanup"]
