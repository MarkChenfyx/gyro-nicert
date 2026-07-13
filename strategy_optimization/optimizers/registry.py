from __future__ import annotations

from typing import Any

from strategy_optimization.optimizers.auto import AutoOptimizer
from strategy_optimization.optimizers.manual_grid import ManualGridOptimizer
from strategy_optimization.optimizers.mock import MockOptimizer
from strategy_optimization.optimizers.optuna_tpe import OptunaOptimizer


METHODS = {
    "manual_grid": {
        "method": "manual_grid",
        "label": "人工调参",
        "description": "按用户输入的 low/high/step 做参数网格搜索。",
        "variant_name": "manual_grid",
        "optimizer": ManualGridOptimizer,
    },
    "auto": {
        "method": "auto",
        "label": "自动优化",
        "description": "由后端优化器自动搜索候选参数，第一版使用确定性候选搜索。",
        "variant_name": "recommended",
        "optimizer": AutoOptimizer,
    },
    "optuna": {
        "method": "optuna",
        "label": "Optuna 智能优化",
        "description": "使用 Optuna TPE 在限定次数内搜索参数组合。",
        "variant_name": "optuna_recommended",
        "optimizer": OptunaOptimizer,
    },
    "mock": {
        "method": "mock",
        "label": "测试优化",
        "description": "离线测试用，不作为主线开发。",
        "variant_name": "recommended",
        "optimizer": MockOptimizer,
    },
}


def resolve_method(options: dict[str, Any] | None = None, backtest_config: dict[str, Any] | None = None) -> str:
    options = dict(options or {})
    backtest_config = dict(backtest_config or {})
    raw = str(options.get("method") or options.get("mode") or "").strip().lower()
    if not raw and str(backtest_config.get("mode") or "").strip().lower() == "mock":
        raw = "mock"
    return raw if raw in METHODS else "manual_grid"


def get_optimizer(method: str):
    resolved = method if method in METHODS else "manual_grid"
    return METHODS[resolved]["optimizer"]()


def variant_for_method(method: str) -> str:
    resolved = method if method in METHODS else "manual_grid"
    return str(METHODS[resolved]["variant_name"])


def list_methods(include_mock: bool = False) -> list[dict[str, str]]:
    rows = []
    for key, payload in METHODS.items():
        if key == "mock" and not include_mock:
            continue
        rows.append(
            {
                "method": str(payload["method"]),
                "label": str(payload["label"]),
                "description": str(payload["description"]),
                "variant_name": str(payload["variant_name"]),
            }
        )
    return rows
