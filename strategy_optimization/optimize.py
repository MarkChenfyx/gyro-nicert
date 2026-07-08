from __future__ import annotations

from typing import Any

from strategy_optimization.optimizers.registry import get_optimizer, resolve_method


def optimize_parameters(
    strategy_code: str,
    class_name: str,
    vt_symbol: str,
    base_parameters: dict[str, Any],
    parameter_space: dict[str, Any],
    backtest_config: dict[str, Any],
    objective: str = "sharpe",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    method = resolve_method(options, backtest_config)
    return get_optimizer(method).optimize(
        strategy_code=strategy_code,
        class_name=class_name,
        vt_symbol=vt_symbol,
        base_parameters=base_parameters,
        parameter_space=parameter_space,
        backtest_config=backtest_config,
        objective=objective,
        options=options,
    )
