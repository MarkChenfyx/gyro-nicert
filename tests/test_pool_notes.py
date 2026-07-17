from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import artifact_service, pool_service


def _prepare_source_run(root: Path, *, variant_name: str = "baseline", variant_result: dict | None = None) -> None:
    run_path = root / "run_1"
    variant_path = run_path / "variants" / variant_name
    variant_path.mkdir(parents=True)
    (run_path / "manifest.json").write_text(json.dumps({"class_name": "ExampleStrategy"}), encoding="utf-8")
    (run_path / "input.json").write_text("{}", encoding="utf-8")
    (run_path / "config.json").write_text(json.dumps({"parameters": {"window": 10}}), encoding="utf-8")
    (run_path / "strategy.py").write_text("class ExampleStrategy:\n    pass\n", encoding="utf-8")
    (variant_path / "result.json").write_text(
        json.dumps(variant_result or {"metrics": {"sharpe": 1.0}}),
        encoding="utf-8",
    )


def _prepare_pool_item(root: Path, *, with_note: bool = True) -> tuple[dict, Path]:
    pool_path = root / "pool_1"
    pool_path.mkdir(parents=True)
    files = {
        "manifest.json": '{"schema":"manifest"}',
        "config.json": '{"parameters":{"window":10}}',
        "result.json": '{"metrics":{"sharpe":1.0}}',
        "strategy.py": "class ExampleStrategy:\n    pass\n",
        "daily_results.csv": "date,net_pnl\n2026-01-01,0\n",
        "trades.csv": "datetime,price\n",
    }
    for filename, content in files.items():
        (pool_path / filename).write_text(content, encoding="utf-8")
    if with_note:
        (pool_path / "notes.md").write_text("原备注", encoding="utf-8")
    item = {"pool_item_id": "pool_1", "pool_path": str(pool_path)}
    return item, pool_path


def test_pool_snapshot_writes_note_and_allows_missing_note(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    pool_root = tmp_path / "pool"
    _prepare_source_run(runs_root)
    monkeypatch.setattr(artifact_service, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(artifact_service, "POOL_STRATEGIES_ROOT", pool_root)

    noted = artifact_service.create_pool_snapshot("run_1", "baseline", note="中文备注\n第二行")
    empty = artifact_service.create_pool_snapshot("run_1", "baseline")

    assert (Path(noted["pool_path"]) / "notes.md").read_text(encoding="utf-8") == "中文备注\n第二行"
    assert (Path(empty["pool_path"]) / "notes.md").read_text(encoding="utf-8") == ""


def test_manual_grid_snapshot_uses_selected_variant_parameters(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    pool_root = tmp_path / "pool"
    _prepare_source_run(
        runs_root,
        variant_name="manual_grid",
        variant_result={
            "recommended": {"parameters": {"window": 24, "threshold": 0.25}},
            "metrics": {"sharpe": 1.5},
        },
    )
    monkeypatch.setattr(artifact_service, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(artifact_service, "POOL_STRATEGIES_ROOT", pool_root)

    snapshot = artifact_service.create_pool_snapshot("run_1", "manual_grid")

    config = json.loads((Path(snapshot["pool_path"]) / "config.json").read_text(encoding="utf-8"))
    assert config["parameters"] == {"window": 24, "threshold": 0.25}


def test_update_notes_preserves_utf8_newlines_and_other_snapshot_files(tmp_path, monkeypatch):
    pool_root = tmp_path / "pool"
    item, pool_path = _prepare_pool_item(pool_root)
    monkeypatch.setattr(pool_service, "POOL_STRATEGIES_ROOT", pool_root)
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: item)
    protected = {
        filename: (pool_path / filename).read_bytes()
        for filename in ("manifest.json", "config.json", "result.json", "strategy.py", "daily_results.csv", "trades.csv")
    }

    result = pool_service.update_pool_item_notes("pool_1", "适合低波动行情\n注意流动性")
    detail = pool_service.get_pool_item_detail("pool_1")

    assert result["note"] == "适合低波动行情\n注意流动性"
    assert detail["notes"] == "适合低波动行情\n注意流动性"
    assert all((pool_path / filename).read_bytes() == content for filename, content in protected.items())


def test_update_notes_can_clear_and_create_missing_file(tmp_path, monkeypatch):
    pool_root = tmp_path / "pool"
    item, pool_path = _prepare_pool_item(pool_root, with_note=False)
    monkeypatch.setattr(pool_service, "POOL_STRATEGIES_ROOT", pool_root)
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: item)

    pool_service.update_pool_item_notes("pool_1", "首次备注")
    assert (pool_path / "notes.md").read_text(encoding="utf-8") == "首次备注"

    pool_service.update_pool_item_notes("pool_1", "")
    assert (pool_path / "notes.md").read_text(encoding="utf-8") == ""
    assert pool_service.get_pool_item_detail("pool_1")["notes"] == ""


def test_update_notes_rejects_path_outside_pool_root(tmp_path, monkeypatch):
    pool_root = tmp_path / "pool"
    outside = tmp_path / "outside"
    outside.mkdir()
    notes_path = outside / "notes.md"
    notes_path.write_text("不可修改", encoding="utf-8")
    item = {"pool_item_id": "pool_1", "pool_path": str(outside)}
    monkeypatch.setattr(pool_service, "POOL_STRATEGIES_ROOT", pool_root)
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: item)

    with pytest.raises(ValueError, match="路径不安全"):
        pool_service.update_pool_item_notes("pool_1", "越界修改")

    assert notes_path.read_text(encoding="utf-8") == "不可修改"


def test_update_notes_missing_pool_item_returns_chinese_404(monkeypatch):
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: None)

    response = TestClient(app).patch("/api/pool/missing/notes", json={"note": "备注"})

    assert response.status_code == 404
    assert response.json()["detail"] == "策略池条目不存在：missing"


def test_pool_note_length_is_limited(monkeypatch):
    monkeypatch.setattr(pool_service.pool_repository, "get_pool_item", lambda pool_item_id: None)

    response = TestClient(app).patch("/api/pool/pool_1/notes", json={"note": "字" * 501})

    assert response.status_code == 422
