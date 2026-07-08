from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import backtesting

from strategy_optimization.optimizers.common import candidate_grid, diagnostic, score_metrics


@dataclass(slots=True)
class ManualGridOptimizer:
    optimizer_name: str = "manual_grid_optimizer"
    optimizer_version: str = "phase7_manual_grid_v1"

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
        options = dict(options or {})
        diagnostics: list[dict[str, Any]] = [diagnostic("info", "manual grid optimizer started")]
        if not str(strategy_code or "").strip():
            return self._failure("strategy_code is empty", diagnostics)
        if not str(class_name or "").strip():
            return self._failure("class_name is empty", diagnostics)
        if not str(vt_symbol or "").strip():
            return self._failure("vt_symbol is empty", diagnostics)

        selected = [str(item) for item in list(options.get("selected_parameters") or []) if str(item).strip()]
        max_trials = max(1, int(options.get("max_trials") or backtest_config.get("max_trials") or 200))
        candidates, grid_diagnostics = candidate_grid(
            dict(base_parameters or {}),
            dict(parameter_space or {}),
            selected_parameters=selected or None,
            max_trials=max_trials,
        )
        diagnostics.extend(grid_diagnostics)
        if not candidates:
            return self._failure("no valid parameter candidates", diagnostics)

        candidate_results: list[dict[str, Any]] = []
        grid_summary: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None
        for index, candidate in enumerate(candidates, start=1):
            result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=dict(candidate["parameters"]),
                config=dict(backtest_config or {}),
            )
            metrics = dict(result.get("metrics") or {})
            score = score_metrics(metrics, objective) if result.get("success") else float("-inf")
            candidate_payload = {
                "label": candidate["label"],
                "parameters": dict(candidate["parameters"]),
                "overrides": dict(candidate["overrides"]),
                "metrics": metrics,
                "score": score,
                "success": bool(result.get("success")),
                "error": result.get("error"),
            }
            candidate_results.append(candidate_payload)
            grid_summary.append(
                {
                    "rank": 0,
                    "label": candidate["label"],
                    "parameters": dict(candidate["overrides"]),
                    "score": score,
                    "success": bool(result.get("success")),
                    "error": result.get("error"),
                }
            )
            if result.get("success") and (best_result is None or score > float(best_result["candidate"]["score"])):
                best_result = {"candidate": candidate_payload, "backtest": result}
            diagnostics.append(diagnostic("info", f"candidate {index}/{len(candidates)} evaluated", label=candidate["label"]))

        successful = [candidate for candidate in candidate_results if candidate["success"]]
        if not successful or best_result is None:
            return {
                "success": False,
                "recommended": None,
                "candidates": candidate_results,
                "grid_summary": grid_summary,
                "best_result": None,
                "diagnostics": diagnostics + [diagnostic("error", "all parameter candidates failed")],
                "optimizer_name": self.optimizer_name,
                "optimizer_version": self.optimizer_version,
                "error": "all parameter candidates failed",
            }
        successful.sort(key=lambda item: float(item.get("score", float("-inf"))), reverse=True)
        rank_by_label = {str(candidate["label"]): rank for rank, candidate in enumerate(successful, start=1)}
        for row in grid_summary:
            row["rank"] = rank_by_label.get(str(row["label"]), 0)
        grid_summary.sort(key=lambda item: (item["rank"] == 0, item["rank"] or 999999))
        recommended = dict(successful[0])
        diagnostics.append(diagnostic("info", f"selected {recommended['label']} as best manual grid parameters"))
        return {
            "success": True,
            "recommended": recommended,
            "candidates": candidate_results,
            "grid_summary": grid_summary,
            "best_result": best_result["backtest"],
            "diagnostics": diagnostics,
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": None,
        }

    def _failure(self, error: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "success": False,
            "recommended": None,
            "candidates": [],
            "grid_summary": [],
            "best_result": None,
            "diagnostics": diagnostics + [diagnostic("error", error)],
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": error,
        }
