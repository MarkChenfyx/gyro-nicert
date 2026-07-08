from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from backend.domain.enums import TaskStatus
from backend.repositories import artifact_repository, strategy_repository
from backend.services import strategy_generation_service


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def _fake_success(source_text: str, options: dict | None = None) -> dict:
    return {
        "success": True,
        "source_text": source_text,
        "strategy_name": "Mock Strategy",
        "class_name": "MockStrategy",
        "strategy_code": "class MockStrategy:\n    pass\n",
        "params": {"fixed_size": 1},
        "spec": {"strategy_name": "Mock Strategy"},
        "diagnostics": [{"stage": "mock", "level": "info", "message": "ok"}],
        "generator_name": "mock",
        "generator_version": "test",
        "error": None,
    }


def _fake_failure(source_text: str, options: dict | None = None) -> dict:
    return {
        "success": False,
        "source_text": source_text,
        "strategy_name": None,
        "class_name": None,
        "strategy_code": None,
        "params": {},
        "spec": {},
        "diagnostics": [{"stage": "mock", "level": "error", "message": "boom"}],
        "generator_name": "mock",
        "generator_version": "test",
        "error": "boom",
    }


def test_generate_and_register_strategy_success(monkeypatch) -> None:
    strategy_dir = None
    monkeypatch.setattr(strategy_generation_service, "generate_strategy_from_text", _fake_success)
    try:
        result = strategy_generation_service.generate_and_register_strategy("demo source")
        task = result["task"]
        strategy = result["strategy"]
        strategy_dir = Path(strategy["code_path"]).parent

        assert task["status"] == TaskStatus.COMPLETED.value
        assert strategy_repository.get_strategy(strategy["strategy_id"]) is not None
        assert Path(strategy["code_path"]).exists()
        assert Path(result["generation_report_path"]).exists()
        artifacts = artifact_repository.list_artifacts("strategy", strategy["strategy_id"])
        artifact_types = {item["artifact_type"] for item in artifacts}
        assert "strategy_code" in artifact_types
        assert "generation_report" in artifact_types
    finally:
        if strategy_dir is not None and strategy_dir.exists():
            shutil.rmtree(strategy_dir)


def test_generate_and_register_strategy_failure_does_not_create_strategy(monkeypatch) -> None:
    monkeypatch.setattr(strategy_generation_service, "generate_strategy_from_text", _fake_failure)
    before = {item["strategy_id"] for item in strategy_repository.list_strategies(limit=1000)}
    result = strategy_generation_service.generate_and_register_strategy("bad source")
    after = {item["strategy_id"] for item in strategy_repository.list_strategies(limit=1000)}

    assert result["task"]["status"] == TaskStatus.FAILED.value
    assert result["strategy"] is None
    assert result["error"] == "boom"
    assert after == before


def test_strategy_generation_service_does_not_import_legacy_internals() -> None:
    source = Path(strategy_generation_service.__file__).read_text(encoding="utf-8")
    assert "legacy_agent_generator" not in source
    assert "LegacyAgentGenerator" not in source
