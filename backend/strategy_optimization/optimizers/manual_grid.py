from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from multiprocessing import get_context
import os
from statistics import median
from typing import Any

import backend.backtesting as backtesting

from backend.strategy_optimization.optimizers.common import candidate_grid, diagnostic, enrich_metrics_with_curve_returns, score_metrics


GRID_DIAGNOSTIC_KEYS = (
    "annual_return",
    "calmar",
    "return_drawdown_ratio",
    "total_net_pnl",
    "total_commission",
    "total_slippage",
    "total_turnover",
    "total_trade_count",
    "profit_days",
    "loss_days",
    "total_days",
    "max_drawdown_value",
    "max_drawdown_pct",
    "max_drawdown_duration",
    "closed_trade_count",
    "trade_win_rate",
    "profit_loss_ratio",
    "profit_factor",
    "gross_expectancy",
    "average_holding_minutes",
    "median_holding_minutes",
    "overnight_trade_count",
)


def _trade_diagnostics(trades: list[dict[str, Any]] | None, *, size: float = 1.0) -> dict[str, Any]:
    """Build a compact round-trip summary without retaining candidate trade details."""
    open_lots: dict[str, list[dict[str, Any]]] = {"long": [], "short": []}
    closed_pnls: list[float] = []
    holding_minutes: list[float] = []
    overnight_trade_count = 0

    for raw_trade in trades or []:
        trade = dict(raw_trade or {})
        direction = str(trade.get("direction") or "").strip().lower()
        offset = str(trade.get("offset") or "").strip().lower()
        side = "long" if direction in {"long", "多"} else "short" if direction in {"short", "空"} else ""
        try:
            price = float(trade.get("price"))
            remaining = float(trade.get("volume") or 0)
            timestamp = datetime.fromisoformat(str(trade.get("datetime") or ""))
        except (TypeError, ValueError):
            continue
        if not side or remaining <= 0:
            continue
        if "open" in offset or "开" in offset:
            open_lots[side].append({"price": price, "remaining": remaining, "datetime": timestamp})
            continue

        closing_side = "short" if side == "long" else "long"
        lots = open_lots[closing_side]
        while remaining > 1e-12 and lots:
            lot = lots[0]
            matched = min(remaining, float(lot["remaining"]))
            pnl_per_unit = price - float(lot["price"]) if closing_side == "long" else float(lot["price"]) - price
            closed_pnls.append(pnl_per_unit * matched * float(size or 1.0))
            duration = max(0.0, (timestamp - lot["datetime"]).total_seconds() / 60.0)
            holding_minutes.append(duration)
            if timestamp.date() > lot["datetime"].date():
                overnight_trade_count += 1
            remaining -= matched
            lot["remaining"] = float(lot["remaining"]) - matched
            if float(lot["remaining"]) <= 1e-12:
                lots.pop(0)

    wins = [value for value in closed_pnls if value > 0]
    losses = [-value for value in closed_pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    average_win = gross_profit / len(wins) if wins else None
    average_loss = gross_loss / len(losses) if losses else None
    return {
        "closed_trade_count": len(closed_pnls),
        "trade_win_rate": (len(wins) / len(closed_pnls) * 100.0) if closed_pnls else None,
        "profit_loss_ratio": (average_win / average_loss) if average_win is not None and average_loss else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "gross_expectancy": (sum(closed_pnls) / len(closed_pnls)) if closed_pnls else None,
        "average_holding_minutes": (sum(holding_minutes) / len(holding_minutes)) if holding_minutes else None,
        "median_holding_minutes": median(holding_minutes) if holding_minutes else None,
        "overnight_trade_count": overnight_trade_count,
    }


def _evaluate_candidate(
    candidate: dict[str, Any],
    *,
    strategy_code: str,
    class_name: str,
    vt_symbol: str,
    backtest_config: dict[str, Any],
    objective: str,
) -> dict[str, Any]:
    """Evaluate one grid candidate in a function that Windows can spawn safely."""
    result = backtesting.run_backtest(
        strategy_code=strategy_code,
        class_name=class_name,
        vt_symbol=vt_symbol,
        parameters=dict(candidate["parameters"]),
        config=dict(backtest_config or {}),
    )
    daily_results = list(result.get("daily_results") or [])
    metrics = enrich_metrics_with_curve_returns(dict(result.get("metrics") or {}), daily_results)
    metrics.update(_trade_diagnostics(list(result.get("trades") or []), size=float(backtest_config.get("size") or 1.0)))
    score = score_metrics(metrics, objective) if result.get("success") else float("-inf")
    return {
        "candidate": {
            "label": candidate["label"],
            "parameters": dict(candidate["parameters"]),
            "overrides": dict(candidate["overrides"]),
            "metrics": metrics,
            "score": score,
            "success": bool(result.get("success")),
            "error": result.get("error"),
        },
        "backtest": result,
        "daily_results": daily_results,
    }


def _worker_count(options: dict[str, Any], backtest_config: dict[str, Any], candidate_count: int) -> int:
    method = str(options.get("method") or "manual_grid").strip().lower()
    if method != "manual_grid":
        return 1
    requested = options.get("max_workers") or backtest_config.get("optimization_workers")
    if requested in {None, ""}:
        requested = os.getenv("GYRO_OPTIMIZATION_MAX_WORKERS")
    if requested in {None, ""}:
        requested = min(4, max(1, (os.cpu_count() or 2) - 1))
    try:
        resolved = int(requested)
    except (TypeError, ValueError):
        resolved = 1
    return max(1, min(resolved, candidate_count))


@dataclass(slots=True)
class ManualGridOptimizer:
    optimizer_name: str = "manual_grid_optimizer"
    optimizer_version: str = "phase9_parallel_grid_v1"

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
        candidate_curves: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None
        best_index: int | None = None
        completed = 0

        def consume(index: int, evaluation: dict[str, Any]) -> None:
            nonlocal best_result, best_index, completed
            candidate_payload = dict(evaluation["candidate"])
            result = dict(evaluation["backtest"])
            daily_results = list(evaluation.get("daily_results") or [])
            metrics = dict(candidate_payload.get("metrics") or {})
            score = float(candidate_payload.get("score", float("-inf")))
            candidate_results.append({"_candidate_index": index, **candidate_payload})
            grid_summary.append(
                {
                    "_candidate_index": index,
                    "rank": 0,
                    "label": candidate_payload["label"],
                    "parameters": dict(candidate_payload["overrides"]),
                    "score": score,
                    "sharpe": metrics.get("sharpe"),
                    "strategy_return": metrics.get("strategy_return"),
                    "benchmark_return": metrics.get("benchmark_return"),
                    "excess_return": metrics.get("excess_return"),
                    **{key: metrics.get(key) for key in GRID_DIAGNOSTIC_KEYS},
                    "success": bool(result.get("success")),
                    "error": result.get("error"),
                }
            )
            if result.get("success") and (
                best_result is None
                or score > float(best_result["candidate"]["score"])
                or (score == float(best_result["candidate"]["score"]) and (best_index is None or index < best_index))
            ):
                best_result = {"candidate": candidate_payload, "backtest": result}
                best_index = index
            if result.get("success") and daily_results:
                candidate_curves.append(
                    {
                        "_candidate_index": index,
                        "label": str(candidate_payload["label"]),
                        "score": score,
                        "daily_results": daily_results,
                    }
                )
            completed += 1
            diagnostics.append(diagnostic("info", f"candidate {index}/{len(candidates)} evaluated", label=candidate_payload["label"]))
            if progress_callback:
                progress_callback(completed, len(candidates), f"参数优化进行中 {completed}/{len(candidates)} 组")

        max_workers = _worker_count(options, backtest_config, len(candidates))
        if max_workers == 1:
            diagnostics.append(diagnostic("info", "manual grid is running sequentially", max_workers=1))
            for index, candidate in enumerate(candidates, start=1):
                consume(
                    index,
                    _evaluate_candidate(
                        candidate,
                        strategy_code=strategy_code,
                        class_name=class_name,
                        vt_symbol=vt_symbol,
                        backtest_config=backtest_config,
                        objective=objective,
                    ),
                )
        else:
            diagnostics.append(
                diagnostic(
                    "info",
                    f"manual grid process pool started with {max_workers} workers",
                    max_workers=max_workers,
                    candidate_count=len(candidates),
                )
            )
            pending: dict[Any, tuple[int, dict[str, Any]]] = {}
            processed: set[int] = set()
            try:
                with ProcessPoolExecutor(max_workers=max_workers, mp_context=get_context("spawn")) as executor:
                    for index, candidate in enumerate(candidates, start=1):
                        future = executor.submit(
                            _evaluate_candidate,
                            candidate,
                            strategy_code=strategy_code,
                            class_name=class_name,
                            vt_symbol=vt_symbol,
                            backtest_config=backtest_config,
                            objective=objective,
                        )
                        pending[future] = (index, candidate)
                    while pending:
                        done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                        for future in done:
                            index, candidate = pending.pop(future)
                            try:
                                evaluation = future.result()
                            except Exception as exc:
                                diagnostics.append(
                                    diagnostic(
                                        "warning",
                                        f"candidate {index} process failed; retrying sequentially: {exc}",
                                        label=candidate["label"],
                                    )
                                )
                                evaluation = _evaluate_candidate(
                                    candidate,
                                    strategy_code=strategy_code,
                                    class_name=class_name,
                                    vt_symbol=vt_symbol,
                                    backtest_config=backtest_config,
                                    objective=objective,
                                )
                            consume(index, evaluation)
                            processed.add(index)
            except Exception as exc:
                diagnostics.append(diagnostic("warning", f"process pool unavailable; continuing sequentially: {exc}"))
                for index, candidate in enumerate(candidates, start=1):
                    if index in processed:
                        continue
                    consume(
                        index,
                        _evaluate_candidate(
                            candidate,
                            strategy_code=strategy_code,
                            class_name=class_name,
                            vt_symbol=vt_symbol,
                            backtest_config=backtest_config,
                            objective=objective,
                        ),
                    )

        candidate_results.sort(key=lambda item: int(item.pop("_candidate_index")))
        grid_summary.sort(key=lambda item: int(item["_candidate_index"]))
        for row in grid_summary:
            row.pop("_candidate_index", None)

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
        for candidate_curve in candidate_curves:
            candidate_curve.pop("_candidate_index", None)
            candidate_curve["rank"] = rank_by_label.get(str(candidate_curve["label"]), 0)
        candidate_curves.sort(key=lambda item: int(item.get("rank") or 999999))
        recommended = dict(successful[0])
        diagnostics.append(diagnostic("info", f"selected {recommended['label']} as best manual grid parameters"))
        return {
            "success": True,
            "recommended": recommended,
            "candidates": candidate_results,
            "grid_summary": grid_summary,
            "candidate_curves": candidate_curves,
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
