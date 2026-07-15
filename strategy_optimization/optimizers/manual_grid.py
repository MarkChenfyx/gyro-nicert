from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import backtesting

from strategy_optimization.optimizers.common import candidate_grid, diagnostic, enrich_metrics_with_curve_returns, score_metrics


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
        progress_callback = options.get("progress_callback")
        if progress_callback is not None and not callable(progress_callback):
            progress_callback = None
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
        if progress_callback:
            progress_callback(0, len(candidates), f"参数优化进行中 0/{len(candidates)} 组")

        candidate_results: list[dict[str, Any]] = []
        grid_summary: list[dict[str, Any]] = []
        top_candidate_curves: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None
        for index, candidate in enumerate(candidates, start=1):
            result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=dict(candidate["parameters"]),
                config=dict(backtest_config or {}),
            )
            daily_results = list(result.get("daily_results") or [])
            metrics = enrich_metrics_with_curve_returns(dict(result.get("metrics") or {}), daily_results)
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
                    "sharpe": metrics.get("sharpe"),
                    "strategy_return": metrics.get("strategy_return"),
                    "benchmark_return": metrics.get("benchmark_return"),
                    "excess_return": metrics.get("excess_return"),
                    "success": bool(result.get("success")),
                    "error": result.get("error"),
                }
            )
            if result.get("success") and (best_result is None or score > float(best_result["candidate"]["score"])):
                best_result = {"candidate": candidate_payload, "backtest": result}
            if result.get("success") and daily_results:
                top_candidate_curves.append(
                    {
                        "label": str(candidate["label"]),
                        "score": score,
                        "daily_results": daily_results,
                    }
                )
                top_candidate_curves.sort(key=lambda item: float(item.get("score", float("-inf"))), reverse=True)
                del top_candidate_curves[10:]
            diagnostics.append(diagnostic("info", f"candidate {index}/{len(candidates)} evaluated", label=candidate["label"]))
            if progress_callback:
                progress_callback(index, len(candidates), f"参数优化进行中 {index}/{len(candidates)} 组")

        successful = [candidate for candidate in candidate_results if candidate["success"]]
        if not successful or best_result is None:
            return {
                "success": False,
                "recommended": None,
                "candidates": candidate_results,
                "grid_summary": grid_summary,
                "candidate_curves": [],
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
        for candidate_curve in top_candidate_curves:
            candidate_curve["rank"] = rank_by_label.get(str(candidate_curve["label"]), 0)
        top_candidate_curves.sort(key=lambda item: int(item.get("rank") or 999999))
        recommended = dict(successful[0])
        diagnostics.append(diagnostic("info", f"selected {recommended['label']} as best manual grid parameters"))
        return {
            "success": True,
            "recommended": recommended,
            "candidates": candidate_results,
            "grid_summary": grid_summary,
            "candidate_curves": top_candidate_curves,
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
            "candidate_curves": [],
            "best_result": None,
            "diagnostics": diagnostics + [diagnostic("error", error)],
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": error,
        }
