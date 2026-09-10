from __future__ import annotations

from types import SimpleNamespace

from backend.services import strategy_generation_service
from backend.strategy_generation.generators.api_strategy_generator import _normalize_strategy_code


def test_strategy_generation_recovers_double_escaped_code_linebreaks():
    expected = "from vnpy_ctastrategy import CtaTemplate\n\nclass EscapedStrategy(CtaTemplate):\n    pass"
    escaped = expected.replace("\n", "\\n")

    assert _normalize_strategy_code(escaped) == expected
    assert _normalize_strategy_code("\\n" + expected) == expected


def test_strategy_generation_reports_api_progress(monkeypatch, tmp_path):
    progress_updates: list[tuple[float, str]] = []
    task = {"task_id": "task_generation", "status": "queued", "progress": 0.0}

    monkeypatch.setattr(strategy_generation_service.task_service, "create_task", lambda *args, **kwargs: dict(task))
    monkeypatch.setattr(strategy_generation_service.task_service, "mark_running", lambda *args, **kwargs: dict(task, status="running"))

    def mark_progress(task_id: str, progress: float, message: str | None = None):
        progress_updates.append((progress, message or ""))
        return dict(task, status="running", progress=progress, message=message)

    monkeypatch.setattr(strategy_generation_service.task_service, "mark_progress", mark_progress)
    monkeypatch.setattr(strategy_generation_service.task_service, "mark_completed", lambda *args, **kwargs: dict(task, status="completed", progress=1.0))
    monkeypatch.setattr(
        strategy_generation_service.natural_language_source_service,
        "read_source_file",
        lambda filename: {"name": filename, "text": "生成一个简单趋势策略"},
    )
    monkeypatch.setattr(
        strategy_generation_service,
        "generate_strategy_from_text",
        lambda text, options=None: {
            "success": True,
            "strategy_name": "ProgressStrategy",
            "class_name": "ProgressStrategy",
            "strategy_code": "class ProgressStrategy:\n    pass\n",
            "source_text": text,
        },
    )
    monkeypatch.setattr(
        strategy_generation_service.strategy_service,
        "register_generated_strategy",
        lambda **kwargs: {
            "strategy_id": "strategy_progress",
            "code_path": str(tmp_path / "strategy.py"),
            **kwargs,
        },
    )
    monkeypatch.setattr(
        strategy_generation_service.artifact_repository,
        "create_artifact",
        lambda **kwargs: kwargs,
    )

    payload = strategy_generation_service.generate_and_register_strategy("progress.txt")

    assert payload["strategy"]["strategy_id"] == "strategy_progress"
    assert [progress for progress, _ in progress_updates] == [0.12, 0.25, 0.78, 0.9]
    assert "API" in progress_updates[1][1]
    assert "API" in progress_updates[2][1]


def test_initial_review_prioritizes_zero_trades_and_reuses_cache(monkeypatch, tmp_path):
    prompts: list[list[dict[str, str]]] = []

    class FakeProvider:
        config = SimpleNamespace(model="test-review-model")

        def complete(self, messages):
            prompts.append(messages)
            return """{
              "verdict": "continue",
              "conclusion": "收益为正，可以继续研究。",
              "trade_assessment": "当前没有成交样本。",
              "code_summary": "发现一个需要人工确认的信号条件。",
              "code_findings": [{
                "severity": "check",
                "title": "突破条件可能无法触发",
                "evidence": "第 3 行：close 与 rolling_high 使用同一根 K 线",
                "suggestion": "确认 rolling_high 是否排除了当前 K 线"
              }],
              "next_step": "先检查突破条件，再重新回测。"
            }"""

    monkeypatch.setattr(strategy_generation_service, "build_provider", lambda options=None: FakeProvider())
    monkeypatch.setattr(
        strategy_generation_service.query_service,
        "get_run_detail",
        lambda run_id: {
            "run": {"run_id": run_id, "strategy_id": "strategy_demo"},
            "strategy": {"strategy_name": "DemoStrategy"},
            "config": {"vt_symbol": "510300.SSE", "interval": "1m"},
            "strategy_code": "class DemoStrategy:\n    def on_bar(self, bar):\n        if bar.close > self.rolling_high: pass\n",
            "baseline_result": {
                "success": True,
                "metrics": {
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "total_days": 120,
                    "total_trade_count": 0,
                    "sharpe": 0,
                },
            },
            "baseline_trades_count": 0,
        },
    )
    monkeypatch.setattr(
        strategy_generation_service.query_service,
        "get_variant_curve",
        lambda run_id, variant_name: {
            "data": [
                {"date": "2026-01-01", "close_price": 100, "pre_close": 99, "net_pnl": 0},
                {"date": "2026-01-02", "close_price": 101, "pre_close": 100, "net_pnl": 0},
            ]
        },
    )
    monkeypatch.setattr(
        strategy_generation_service,
        "_review_cache_path",
        lambda run_id: tmp_path / f"{run_id}.json",
    )

    first = strategy_generation_service.create_initial_review("run_demo")
    second = strategy_generation_service.create_initial_review("run_demo")

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["review"]["verdict"] == "insufficient"
    assert first["review"]["conclusion"] == "本次回测成交 0 次，没有可用于判断策略有效性的交易样本。"
    assert first["review"]["code_findings"][0]["evidence"].startswith("第 3 行")
    assert len(prompts) == 1
    assert '"trade_count": 0' in prompts[0][1]["content"]
    assert "0003:         if bar.close" in prompts[0][1]["content"]


def test_initial_review_allows_optimization_after_ten_trades_without_confirmed_issue():
    review = {
        "verdict": "revise",
        "conclusion": "收益暂时跑输基准。",
        "trade_assessment": "已有十余次成交。",
        "code_summary": "存在一项轻微命名风险。",
        "code_findings": [
            {
                "severity": "check",
                "title": "名称需要确认",
                "evidence": "第 9 行：注释中的标的名称不同",
                "suggestion": "后续统一命名",
            }
        ],
        "next_step": "后续可以调整参数。",
    }

    checked = strategy_generation_service._enforce_trade_gate(review, 12)

    assert checked["verdict"] == "continue"
    assert checked["conclusion"].startswith("本次成交 12 次")
    assert checked["next_step"].startswith("可以进入参数优化")
