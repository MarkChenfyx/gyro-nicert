import json
import sqlite3
from pathlib import Path

import pytest

from backend.core import paths
from backend.data_manager import database
from backend.repositories import strategy_repository, run_repository, variant_repository, artifact_repository
from backend.repositories import pool_repository, portfolio_repository
from backend.services import artifact_service, query_service
from scripts.init_db import APP_SCHEMA


def test_new_artifacts_survive_installation_move(tmp_path, monkeypatch):
    root = tmp_path / "original"
    storage = root / "storage"
    storage.mkdir(parents=True)
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    monkeypatch.setattr(paths, "STORAGE_ROOT", storage)
    db = storage / "app.sqlite"
    monkeypatch.setattr(database, "APP_DB_PATH", db)
    with sqlite3.connect(db) as c:
        c.executescript(APP_SCHEMA)
    c.close()
    code = storage / "strategy.py"
    code.write_text("# portable strategy", encoding="utf-8")
    strategy_repository.create_strategy("s", "demo", "demo", "1", "demo.py", "code", "", "Demo", str(code))
    run = storage / "runtime" / "runs" / "r"
    run.mkdir(parents=True)
    (run / "strategy.py").write_text("# portable strategy", encoding="utf-8")
    artifact_service._write_json(run / "manifest.json", {"run_path": str(run)})
    result = run / "result.json"
    artifact_service._write_json(result, {"metrics": {"sharpe": 1}})
    run_repository.create_run("r", "s", None, "baseline", "completed", str(run))
    variant_repository.create_variant("v", "r", "baseline", None, None, str(result))
    artifact_repository.create_artifact("run", "r", "result", result)
    pool_repository.create_pool_item("pool", "s", "r", "v", str(run), "demo")
    portfolio_repository.create_snapshot(snapshot_id="snapshot", portfolio_id="portfolio", definition_hash="hash",
                                         source_hashes={}, metrics={}, artifact_path=str(run))
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT code_path FROM strategies").fetchone()[0] == "storage/strategy.py"
        assert not Path(c.execute("SELECT runtime_path FROM runs").fetchone()[0]).is_absolute()
    c.close()
    assert json.loads((run / "manifest.json").read_text())["run_path"].startswith("storage/")
    moved = tmp_path / "moved"
    root.rename(moved)
    monkeypatch.setattr(paths, "PROJECT_ROOT", moved)
    monkeypatch.setattr(paths, "STORAGE_ROOT", moved / "storage")
    monkeypatch.setattr(database, "APP_DB_PATH", moved / "storage" / "app.sqlite")
    detail = query_service.get_run_detail("r")
    assert detail["strategy_code"] == "# portable strategy"
    assert Path(strategy_repository.get_strategy("s")["code_path"]).is_file()
    assert Path(detail["manifest"]["run_path"]).is_dir()
    assert Path(artifact_repository.list_artifacts("run", "r")[0]["path"]).is_file()
    assert Path(pool_repository.get_pool_item("pool")["pool_path"]).is_dir()
    assert Path(portfolio_repository.get_snapshot("snapshot")["artifact_path"]).is_dir()


def test_artifact_resolution_rejects_escape():
    with pytest.raises(ValueError):
        paths.resolved_path("storage/../../outside")


def test_path_conversion_does_not_rewrite_source_or_notes():
    value = {"source_text": str(paths.PROJECT_ROOT / "storage" / "example"), "notes": "unchanged"}
    assert paths.path_fields(value, storing=True) == value
