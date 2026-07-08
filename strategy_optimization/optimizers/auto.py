from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strategy_optimization.optimizers.manual_grid import ManualGridOptimizer


@dataclass(slots=True)
class AutoOptimizer:
    optimizer_name: str = "auto_parameter_optimizer"
    optimizer_version: str = "phase7_auto_v1"

    def optimize(
        self,
        *,
        strategy_code: str,
        class_name: str,
        vt_symbol: str,
        base_parameters: dict[str, Any],
        parameter_space: dict[str, Any],
        backtest_config: dict[str, Any],
        objective: str = "sharpe",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        delegated = ManualGridOptimizer(
            optimizer_name=self.optimizer_name,
            optimizer_version=self.optimizer_version,
        ).optimize(
            strategy_code=strategy_code,
            class_name=class_name,
            vt_symbol=vt_symbol,
            base_parameters=base_parameters,
            parameter_space=parameter_space,
            backtest_config=backtest_config,
            objective=objective,
            options=options,
        )
        delegated["diagnostics"] = [
            {"level": "info", "message": "auto optimizer currently uses deterministic candidate search"}
        ] + list(delegated.get("diagnostics") or [])
        delegated["optimizer_name"] = self.optimizer_name
        delegated["optimizer_version"] = self.optimizer_version
        return delegated
