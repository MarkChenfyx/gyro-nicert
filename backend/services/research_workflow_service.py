from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from backtesting import run_backtest
from backend.domain.enums import TaskType
from backend.repositories import strategy_repository
from backend.services import run_service, strategy_generation_service, strategy_service, task_service


def _read_generation_report(strategy: dict[str, Any]) -> dict[str, Any]:
    code_path = Path(str(strategy.get("code_path") or ""))
    if not code_path.exists():
        raise FileNotFoundError(f"strategy code not found: {strategy.get('strategy_id')}")
    report_path = code_path.parent / "generation_report.json"
    if not report_path.exists() or not report_path.is_file():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def _build_backtest_config(config_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
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


def _execution_meta(mode: str) -> dict[str, Any]:
    normalized = str(mode or "real").lower()
    return {
        "execution_mode": "mock_baseline" if normalized == "mock" else "real_backtest",
        "is_real_backtest": normalized == "real",
    }


def _create_baseline_from_strategy_payload(
    *,
    strategy: dict[str, Any],
    generated: dict[str, Any],
    config_payload: dict[str, Any] | None = None,
    baseline_result_payload: dict[str, Any] | None = None,
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    config = _build_backtest_config(config_payload)
    execution = _execution_meta(str(config.get("mode") or "real"))
    backtest_result = run_backtest(
        strategy_code=str(generated.get("strategy_code") or ""),
        class_name=str(generated.get("class_name") or strategy.get("class_name") or ""),
        vt_symbol=str(config.get("vt_symbol") or "510300.SSE"),
        parameters=dict(generated.get("params") or {}),
        config=config,
    )
    if not backtest_result.get("success"):
        task = task_service.create_task(TaskType.BACKTEST.value, message="Backtest queued", related_strategy_id=str(strategy["strategy_id"]))
        task = task_service.mark_failed(
            task["task_id"],
            error=str(backtest_result.get("error") or "backtest failed"),
            message="Backtest failed",
        )
        return {
            "baseline": None,
            "backtest": backtest_result,
            "backtest_task": task,
            **execution,
            "error": backtest_result.get("error") or "backtest failed",
        }

    result_payload = dict(backtest_result)
    result_payload.pop("daily_results", None)
    result_payload.pop("trades", None)
    baseline = run_service.create_baseline_run(
        strategy=strategy,
        source_text=str(generated.get("source_text") or strategy.get("source_text") or ""),
        config_payload={
            **config,
            **execution,
        },
        strategy_code=str(generated.get("strategy_code") or ""),
        result_payload=dict(baseline_result_payload or result_payload),
        daily_results=daily_results if daily_results is not None else backtest_result.get("daily_results"),
        trades=trades if trades is not None else backtest_result.get("trades"),
    )
    return {
        "baseline": baseline,
        "backtest": backtest_result,
        **execution,
        "error": None,
    }


def create_strategy_research_run(
    source_filename: str,
    options: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
    baseline_result_payload: dict[str, Any] | None = None,
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    generation = strategy_generation_service.generate_and_register_strategy(source_filename, options=options)
    if generation.get("strategy") is None:
        return {
            "generation": generation,
            "baseline": None,
            "error": generation.get("error") or "strategy generation failed",
        }

    strategy = dict(generation["strategy"])
    generated = dict(generation["generation"])
    baseline_payload = _create_baseline_from_strategy_payload(
        strategy=strategy,
        generated=generated,
        config_payload=config_payload,
        baseline_result_payload=baseline_result_payload,
        daily_results=daily_results,
        trades=trades,
    )
    return {
        "generation": generation,
        **baseline_payload,
    }


def create_baseline_run_for_strategy(
    strategy_id: str,
    config_payload: dict[str, Any] | None = None,
    baseline_result_payload: dict[str, Any] | None = None,
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    strategy = strategy_repository.get_strategy(strategy_id)
    if strategy is None:
        raise FileNotFoundError(f"Strategy not found: {strategy_id}")
    report = _read_generation_report(strategy)
    code_path = Path(str(strategy.get("code_path") or ""))
    generated = {
        "source_text": strategy.get("source_text") or "",
        "strategy_code": code_path.read_text(encoding="utf-8"),
        "class_name": str(report.get("class_name") or strategy.get("class_name") or ""),
        "params": dict(report.get("params") or {}),
    }
    return _create_baseline_from_strategy_payload(
        strategy=dict(strategy),
        generated=generated,
        config_payload=config_payload,
        baseline_result_payload=baseline_result_payload,
        daily_results=daily_results,
        trades=trades,
    )


def create_baseline_run_from_manual_code(
    strategy_name: str,
    strategy_code: str,
    config_payload: dict[str, Any] | None = None,
    baseline_result_payload: dict[str, Any] | None = None,
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    generated: dict[str, Any] = {}
    try:
        strategy = strategy_service.register_manual_strategy(
            strategy_name=strategy_name,
            code=strategy_code,
        )
        executable_code = Path(str(strategy["code_path"])).read_text(encoding="utf-8")
        generated = {
            "success": True,
            "source_type": "manual_code",
            "input_mode": "manual_code",
            "strategy_name": str(strategy_name or "").strip(),
            "source_text": str(strategy_code or ""),
            "strategy_code": executable_code,
            "class_name": str(strategy.get("class_name") or ""),
            "params": {},
            "diagnostics": [],
        }
        baseline_payload = _create_baseline_from_strategy_payload(
            strategy=dict(strategy),
            generated=generated,
            config_payload=config_payload,
            baseline_result_payload=baseline_result_payload,
            daily_results=daily_results,
            trades=trades,
        )
        return {
            "generation": {
                "task": None,
                "strategy": strategy,
                "generation": generated,
                "generation_report_path": "",
                "generation_report_artifact": None,
                "error": None,
            },
            **baseline_payload,
        }
    except Exception as exc:
        return {
            "generation": {
                "task": None,
                "strategy": None,
                "generation": {
                    **generated,
                    "success": False,
                    "source_type": "manual_code",
                    "input_mode": "manual_code",
                    "strategy_name": str(strategy_name or "").strip(),
                    "strategy_code": str(strategy_code or ""),
                },
                "generation_report_path": "",
                "generation_report_artifact": None,
                "error": str(exc),
            },
            "baseline": None,
            "backtest": {
                "success": False,
                "error": str(exc),
                "metrics": {},
                "daily_results": [],
                "trades": [],
            },
            "backtest_task": None,
            **_execution_meta(str((config_payload or {}).get("mode") or "real")),
            "error": str(exc),
        }
