from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MockOptimizer:
    optimizer_name: str = "mock_parameter_optimizer"
    optimizer_version: str = "phase7_mock_v1"

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
        candidate = {
            "label": "mock",
            "parameters": dict(base_parameters or {}),
            "overrides": {},
            "metrics": {"objective": objective, "score": 0.0, "sharpe": 0.0},
            "score": 0.0,
            "success": True,
            "error": None,
        }
        return {
            "success": True,
            "recommended": candidate,
            "candidates": [candidate],
            "grid_summary": [{"rank": 1, "label": "mock", "parameters": {}, "score": 0.0, "success": True, "error": None}],
            "best_result": {
                "success": True,
                "metrics": candidate["metrics"],
                "daily_results": [{"date": "1970-01-01", "balance": float(dict(backtest_config or {}).get("capital") or 100000.0), "close_price": 1.0}],
                "trades": [],
                "diagnostics": [{"level": "info", "message": "mock optimizer returned base parameters"}],
                "error": None,
            },
            "diagnostics": [{"level": "info", "message": "mock optimizer returned base parameters"}],
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": None,
        }

