from __future__ import annotations

from typing import Any


OPTIMIZER_NAME = "mock_parameter_optimizer"
OPTIMIZER_VERSION = "phase3_5_boundary_v1"


def _diagnostic(level: str, message: str) -> dict[str, str]:
    return {"level": level, "message": message}


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
    mode = str(dict(options or {}).get("mode") or dict(backtest_config or {}).get("mode") or "").strip().lower()
    if mode == "mock":
        parameters = dict(base_parameters or {})
        candidate = {
            "parameters": parameters,
            "metrics": {"objective": objective, "score": 0.0, "sharpe": 0.0},
        }
        return {
            "success": True,
            "recommended": candidate,
            "candidates": [candidate],
            "grid_summary": [{"rank": 1, "parameters": parameters, "score": 0.0}],
            "diagnostics": [_diagnostic("info", "mock mode returned base parameters as recommendation")],
            "optimizer_name": OPTIMIZER_NAME,
            "optimizer_version": OPTIMIZER_VERSION,
            "error": None,
        }
    return {
        "success": False,
        "recommended": None,
        "candidates": [],
        "grid_summary": [],
        "diagnostics": [_diagnostic("error", "real parameter optimization is not implemented in Phase 3.5")],
        "optimizer_name": OPTIMIZER_NAME,
        "optimizer_version": OPTIMIZER_VERSION,
        "error": "parameter optimization is not implemented; pass options['mode']='mock' or backtest_config['mode']='mock'",
    }

