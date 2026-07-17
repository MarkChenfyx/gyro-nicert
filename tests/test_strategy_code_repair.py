from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.api import strategy_api
from backend.main import app
from backend.services import research_workflow_service
from backend.strategy_generation import repair as repair_module


class _FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload
        self.messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return json.dumps(self.payload, ensure_ascii=False)


def test_ai_repair_returns_model_code_after_open_volume_validation(monkeypatch):
    repaired_code = "class UploadedStrategy:\n    fixed_size = 1\n    def trade(self, price):\n        self.buy(price, self.fixed_size)"
    provider = _FakeProvider(
        {
            "status": "runnable",
            "success": True,
            "can_backtest": True,
            "strategy_code": repaired_code,
            "changes": ["完成最小修正"],
            "reasons": [],
            "warnings": [],
            "blocking_issues": [],
            "error": None,
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
        vt_symbol="511380.SSE",
        interval="1m",
    )

    assert result["status"] == "runnable"
    assert result["success"] is True
    assert result["strategy_code"] == repaired_code
    assert result["changes"] == ["完成最小修正"]
    assert result["warnings"] == []
    assert "class UploadedStrategy: pass" in provider.messages[1]["content"]
    assert "511380.SSE" in provider.messages[1]["content"]


def test_ai_repair_rejects_target_size_open_volume(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "runnable",
            "strategy_code": "class UploadedStrategy:\n    fixed_size = 1\n    target_size = 100\n    def trade(self, price):\n        self.buy(price, self.target_size)\n",
            "changes": ["已修正策略代码"],
            "reasons": [],
            "error": None,
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["status"] == "failed"
    assert "必须严格使用 self.fixed_size" in result["error"]


def test_ai_repair_rejects_empty_model_code(monkeypatch):
    provider = _FakeProvider({
        "status": "runnable",
        "success": True,
        "can_backtest": True,
        "strategy_code": "",
        "changes": [],
        "warnings": [],
        "blocking_issues": [],
    })
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["strategy_code"] == ""
    assert "没有返回可用代码" in result["error"]


def test_ai_repair_rejects_blocking_runner_result(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "failed",
            "success": False,
            "can_backtest": False,
            "strategy_code": "class invalid_name(1): pass",
            "changes": ["converted runner"],
            "reasons": ["上传的是启动脚本，但没有提供其导入的真实策略源码。"],
            "warnings": [],
            "blocking_issues": [],
            "error": "上传的是启动脚本，但没有提供其导入的真实策略源码。",
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="run_strategy(1)",
        strategy_code="from missing_strategy import Strategy",
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["can_backtest"] is False
    assert result["strategy_code"] == ""
    assert "没有提供" in result["error"]


def test_ai_repair_requires_structured_status(monkeypatch):
    provider = _FakeProvider(
        {
            "success": True,
            "strategy_code": "class UploadedStrategy: pass",
            "changes": [],
            "warnings": [],
            "blocking_issues": [],
            "error": None,
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert "格式错误" in result["error"]


def test_ai_repair_localizes_english_result_text(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "failed",
            "success": False,
            "can_backtest": False,
            "strategy_code": "",
            "changes": ["Converted the runner."],
            "reasons": ["Review the dependency.", "The imported strategy source is missing."],
            "warnings": [],
            "blocking_issues": [],
            "error": "The code cannot be backtested.",
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="from missing_strategy import Strategy",
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["changes"] == ["AI 已完成代码修正"]
    assert result["reasons"] == ["AI 判断代码仍有需要人工处理的问题", "AI 判断代码仍有需要人工处理的问题"]
    assert result["error"] == "AI 明确表示代码修正失败"


def test_ai_repair_warning_never_marks_code_runnable(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "warning",
            "strategy_code": "class UploadedStrategy: pass",
            "changes": ["已完成可自动处理的部分"],
            "reasons": ["仍依赖本地 schedule_path 和 Parquet 文件"],
            "error": None,
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["status"] == "warning"
    assert result["success"] is False
    assert result["can_backtest"] is False
    assert result["strategy_code"] == "class UploadedStrategy: pass"
    assert result["reasons"] == ["仍依赖本地 schedule_path 和 Parquet 文件"]


def test_ai_repair_downgrades_inconsistent_runnable_with_reasons(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "runnable",
            "strategy_code": "class UploadedStrategy: pass",
            "changes": [],
            "reasons": ["仍需读取本地 CSV 文件"],
            "error": None,
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["status"] == "warning"
    assert result["success"] is False
    assert result["reasons"] == ["仍需读取本地 CSV 文件"]


def test_ai_repair_rejects_malformed_reason_field(monkeypatch):
    provider = _FakeProvider(
        {
            "status": "warning",
            "strategy_code": "class UploadedStrategy: pass",
            "changes": [],
            "reasons": "仍需人工处理",
        }
    )
    monkeypatch.setattr(repair_module, "build_provider", lambda options=None: provider)

    result = repair_module.repair_strategy_code(
        strategy_name="UploadedStrategy",
        strategy_code="class UploadedStrategy: pass",
    )

    assert result["status"] == "failed"
    assert "格式错误" in result["error"]


def test_ai_repair_requires_source_code():
    result = repair_module.repair_strategy_code(strategy_name="Empty", strategy_code="")

    assert result == {
        "status": "failed",
        "success": False,
        "can_backtest": False,
        "strategy_code": "",
        "changes": [],
        "reasons": ["策略代码为空"],
        "warnings": [],
        "blocking_issues": [],
        "error": "策略代码为空",
    }


def test_ai_repair_api_returns_repaired_code(monkeypatch):
    monkeypatch.setattr(
        strategy_api,
        "repair_strategy_code",
        lambda **kwargs: {
            "status": "runnable",
            "success": True,
            "strategy_code": "REPAIRED_CODE",
            "changes": [],
            "warnings": [],
            "error": None,
        },
    )

    response = TestClient(app).post(
        "/api/strategies/repair",
        json={
            "strategy_name": "UploadedStrategy",
            "strategy_code": "ORIGINAL_CODE",
            "vt_symbol": "511380.SSE",
            "interval": "1m",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "runnable"
    assert response.json()["strategy_code"] == "REPAIRED_CODE"


def test_manual_baseline_uses_registered_executable_code(monkeypatch, tmp_path):
    captured: dict = {}
    executable_path = tmp_path / "strategy.py"
    executable_path.write_text("class UploadedStrategy:\n    fixed_size = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        research_workflow_service.strategy_service,
        "register_manual_strategy",
        lambda **kwargs: {
            "strategy_id": "strategy_repaired",
            "class_name": "UploadedStrategy",
            "code_path": str(executable_path),
        },
    )

    def fake_create_baseline(**kwargs):
        captured.update(kwargs)
        return {"baseline": {"run": {"run_id": "run_repaired"}}, "error": None}

    monkeypatch.setattr(research_workflow_service, "_create_baseline_from_strategy_payload", fake_create_baseline)

    result = research_workflow_service.create_baseline_run_from_manual_code(
        strategy_name="UploadedStrategy",
        strategy_code="REPAIRED_CODE",
    )

    assert result["baseline"]["run"]["run_id"] == "run_repaired"
    assert captured["generated"]["source_text"] == "REPAIRED_CODE"
    assert captured["generated"]["strategy_code"] == "class UploadedStrategy:\n    fixed_size = 1\n"
