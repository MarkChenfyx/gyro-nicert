from __future__ import annotations

from typing import Any

from backtesting import run_backtest
from backend.domain.enums import TaskType
from backend.services import run_service, strategy_generation_service
from backend.services import task_service


def create_strategy_research_run(
    source_text: str,
    options: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
    baseline_result_payload: dict[str, Any] | None = None,
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    generation = strategy_generation_service.generate_and_register_strategy(source_text, options=options)
    if generation.get("strategy") is None:
        return {
            "generation": generation,
            "baseline": None,
            "error": generation.get("error") or "strategy generation failed",
        }

    strategy = dict(generation["strategy"])
    generated = dict(generation["generation"])
    config = {
        "vt_symbol": "510300.SSE",
        "interval": "1m",
        "mode": "real",
        "capital": 100000.0,
        "rate": 0.000045,
        "slippage": 0.001,
        "size": 1.0,
        "pricetick": 0.001,
        **{key: value for key, value in dict(config_payload or {}).items() if value is not None},
    }
    mode = str(config.get("mode") or "real").lower()
    backtest_result = run_backtest(
        strategy_code=str(generated.get("strategy_code") or ""),
        class_name=str(generated.get("class_name") or ""),
        vt_symbol=str(config.get("vt_symbol") or "510300.SSE"),
        parameters=dict(generated.get("params") or {}),
        config=config,
    )
    if not backtest_result.get("success"):
        task = task_service.create_task(TaskType.BACKTEST.value, message="Backtest queued", related_strategy_id=strategy["strategy_id"])
        task = task_service.mark_failed(
            task["task_id"],
            error=str(backtest_result.get("error") or "backtest failed"),
            message="Backtest failed",
        )
        return {
            "generation": generation,
            "baseline": None,
            "backtest": backtest_result,
            "backtest_task": task,
            "execution_mode": "mock_baseline" if mode == "mock" else "real_backtest",
            "is_real_backtest": mode == "real",
            "error": backtest_result.get("error") or "backtest failed",
        }

    result_payload = dict(backtest_result)
    result_payload.pop("daily_results", None)
    result_payload.pop("trades", None)
    baseline = run_service.create_baseline_run(
        strategy_id=strategy["strategy_id"],
        strategy_name=strategy["strategy_name"],
        source_text=str(generated.get("source_text") or source_text),
        config_payload={
            **config,
            "execution_mode": "mock_baseline" if mode == "mock" else "real_backtest",
            "is_real_backtest": mode == "real",
        },
        strategy_code=str(generated.get("strategy_code") or ""),
        result_payload=dict(baseline_result_payload or result_payload),
        daily_results=daily_results if daily_results is not None else backtest_result.get("daily_results"),
        trades=trades if trades is not None else backtest_result.get("trades"),
    )
    return {
        "generation": generation,
        "baseline": baseline,
        "backtest": backtest_result,
        "execution_mode": "mock_baseline" if mode == "mock" else "real_backtest",
        "is_real_backtest": mode == "real",
        "error": None,
    }
