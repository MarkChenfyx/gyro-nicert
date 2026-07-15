from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from backend.main import app
from backend.repositories import run_repository
from backend.services import optimization_service


def _connection_factory(path):
    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    return connect


def _create_summary_schema(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE strategies (
                strategy_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                strategy_family TEXT,
                strategy_version TEXT,
                source_filename TEXT
            );
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
            """
        )


def test_run_summary_joins_strategy_and_counts_variants(tmp_path, monkeypatch):
    db_path = tmp_path / "app.sqlite"
    _create_summary_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO strategies VALUES (?, ?, ?, ?, ?)",
            ("strategy_1", "Moving Average", "ma", "v1", "ma.py"),
        )
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_1", "strategy_1", "task_1", "baseline", "completed", str(tmp_path / "run_1"), "2026-01-02", "2026-01-02"),
        )
        connection.executemany(
            "INSERT INTO run_variants VALUES (?, ?, ?)",
            [("variant_1", "run_1", "baseline"), ("variant_2", "run_1", "manual_grid")],
        )
    monkeypatch.setattr(run_repository, "get_app_db_connection", _connection_factory(db_path))

    summary = run_repository.list_run_summaries()[0]

    assert summary["strategy_name"] == "Moving Average"
    assert summary["strategy_family"] == "ma"
    assert summary["source_filename"] == "ma.py"
    assert summary["variant_count"] == 2


def test_optimizable_runs_reads_config_without_per_run_strategy_query(tmp_path, monkeypatch):
    run_path = tmp_path / "run_1"
    run_path.mkdir()
    (run_path / "config.json").write_text(
        json.dumps({"symbol": "511380", "exchange": "SSE", "interval": "1m", "mode": "real"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_repository,
        "list_run_summaries",
        lambda limit=50: [{
            "run_id": "run_1",
            "strategy_id": "strategy_1",
            "strategy_name": "Moving Average",
            "strategy_family": "ma",
            "strategy_version": "v1",
            "source_filename": "ma.py",
            "runtime_path": str(run_path),
            "variant_count": 2,
        }],
    )
    monkeypatch.setattr(
        optimization_service.strategy_repository,
        "get_strategy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected strategy query")),
    )

    run = optimization_service.list_optimizable_runs()["runs"][0]

    assert run["vt_symbol"] == "511380.SSE"
    assert run["interval"] == "1m"
    assert run["variant_count"] == 2


def test_runs_api_defaults_to_50_and_accepts_explicit_limit(monkeypatch):
    seen: list[int] = []

    def fake_list(limit=50):
        seen.append(limit)
        return {"runs": []}

    monkeypatch.setattr(optimization_service, "list_optimizable_runs", fake_list)
    client = TestClient(app)

    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/runs", params={"limit": 7}).status_code == 200
    assert seen == [50, 7]
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/runs", params={"limit": 1001}).status_code == 422
