from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from backend.main import app
from backend.repositories import task_repository


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
