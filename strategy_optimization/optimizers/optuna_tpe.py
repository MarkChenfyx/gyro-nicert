from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import optuna

import backtesting
from strategy_optimization.optimizers.common import (
    diagnostic,
    enrich_metrics_with_curve_returns,
    score_metrics,
    values_from_range,
)


def _suggest(trial: optuna.Trial, name: str, spec: Any, base_value: Any) -> Any:
    """Translate the workbench search-space contract into an Optuna suggestion."""
    if isinstance(spec, (list, tuple)) or (isinstance(spec, dict) and isinstance(spec.get("values"), list)):
        choices = values_from_range(spec, base_value)
        if not choices:
            raise ValueError(f"parameter {name} has no candidate values")
        return trial.suggest_categorical(name, choices)
    if not isinstance(spec, dict):
        return trial.suggest_categorical(name, [spec])

    low = spec.get("low")
    high = spec.get("high")
    step = spec.get("step")
    if low in {None, ""} or high in {None, ""}:
        raise ValueError(f"parameter {name} requires low and high")
    value_type = str(spec.get("type") or ("int" if isinstance(base_value, int) and not isinstance(base_value, bool) else "float")).lower()
    if value_type == "int":
        return trial.suggest_int(name, int(float(low)), int(float(high)), step=max(1, int(float(step or 1))))
    if str(spec.get("scale") or "").lower() == "log" and float(low) > 0:
        return trial.suggest_float(name, float(low), float(high), log=True)
    float_step = float(step) if step not in {None, ""} else None
    return trial.suggest_float(name, float(low), float(high), step=float_step)


def _violates_common_constraints(parameters: dict[str, Any]) -> str | None:
    """Reject obviously invalid indicator relationships before running a backtest."""
    pairs = [
        ("fast_window", "slow_window"),
        ("fast_ma", "slow_ma"),
        ("macd_fast", "macd_slow"),
        ("rsi_exit", "rsi_entry"),
    ]
    for lower, upper in pairs:
        if lower in parameters and upper in parameters:
            try:
                if float(parameters[lower]) >= float(parameters[upper]):
                    return f"constraint requires {lower} < {upper}"
            except (TypeError, ValueError):
                pass
    if "rsi_entry" in parameters and "rsi_cap" in parameters:
        try:
            if float(parameters["rsi_entry"]) >= float(parameters["rsi_cap"]):
                return "constraint requires rsi_entry < rsi_cap"
        except (TypeError, ValueError):
            pass
    return None


def _map_virtual_parameters(values: dict[str, Any], specs: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    mapped = dict(values)
    virtual_values: dict[str, Any] = {}
    for name, spec in specs.items():
        if name not in mapped:
            continue
        value = mapped.pop(name)
        virtual_values[name] = value
        maps_to = list(spec.get("maps_to") or [])
        if len(maps_to) == 2 and isinstance(value, str) and ":" in value:
            hour, minute = value.split(":", 1)
            mapped[str(maps_to[0])] = int(hour)
            mapped[str(maps_to[1])] = int(minute)
    return mapped, virtual_values


def _constraint_violation(
    constraints: list[dict[str, Any]],
    parameters: dict[str, Any],
    virtual_values: dict[str, Any],
) -> str | None:
    values = {**parameters, **virtual_values}
    operators = {
        "<": lambda left, right: left < right,
        "<=": lambda left, right: left <= right,
        ">": lambda left, right: left > right,
        ">=": lambda left, right: left >= right,
        "==": lambda left, right: left == right,
    }
    for item in constraints:
        left_name = str(item.get("left") or "")
        operator = str(item.get("operator") or "")
        right_token = str(item.get("right") or "")
        if left_name not in values or operator not in operators:
            continue
        right: Any = values.get(right_token)
        if right is None:
            try:
                right = float(right_token)
            except ValueError:
                continue
        try:
            if not operators[operator](values[left_name], right):
                return str(item.get("expression") or f"{left_name} {operator} {right_token}")
        except TypeError:
            continue
    return None


@dataclass(slots=True)
class OptunaOptimizer:
    optimizer_name: str = "optuna_tpe_optimizer"
    optimizer_version: str = "phase8_optuna_tpe_v1"

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
        diagnostics: list[dict[str, Any]] = [diagnostic("info", "Optuna TPE optimizer started")]
        if not str(strategy_code or "").strip() or not str(class_name or "").strip() or not str(vt_symbol or "").strip():
            return self._failure("strategy_code, class_name and vt_symbol are required", diagnostics)

        virtual_specs = {
            str(item.get("name")): dict(item)
            for item in options.get("virtual_parameters") or []
            if item.get("name") and item.get("choices")
        }
        selected = [str(item) for item in options.get("selected_parameters") or [*parameter_space.keys(), *virtual_specs.keys()]]
        selected = [name for name in selected if name in parameter_space or name in virtual_specs]
        if not selected:
            return self._failure("no valid parameters selected", diagnostics)

        max_trials = max(1, int(options.get("max_trials") or backtest_config.get("max_trials") or 100))
        progress_callback = options.get("progress_callback") if callable(options.get("progress_callback")) else None
        seed = int(options.get("seed") or 42)
        sampler = optuna.samplers.TPESampler(seed=seed, multivariate=len(selected) > 1)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        candidate_results: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None

        if progress_callback:
            progress_callback(0, max_trials, f"Optuna 参数优化进行中 0/{max_trials} 组")

        def evaluate(trial: optuna.Trial) -> float:
            nonlocal best_result
            suggested = {
                name: (
                    trial.suggest_categorical(name, list(virtual_specs[name]["choices"]))
                    if name in virtual_specs
                    else _suggest(trial, name, parameter_space[name], base_parameters.get(name))
                )
                for name in selected
            }
            mapped_overrides, virtual_values = _map_virtual_parameters(suggested, virtual_specs)
            parameters = {**base_parameters, **mapped_overrides}
            violation = _violates_common_constraints(parameters)
            violation = violation or _constraint_violation(list(options.get("constraints") or []), parameters, virtual_values)
            if violation:
                trial.set_user_attr("error", violation)
                raise optuna.TrialPruned(violation)

            result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=parameters,
                config=dict(backtest_config or {}),
            )
            metrics = enrich_metrics_with_curve_returns(
                dict(result.get("metrics") or {}),
                list(result.get("daily_results") or []),
            )
            success = bool(result.get("success"))
            score = score_metrics(metrics, objective) if success else float("-inf")
            payload = {
                "label": f"trial_{trial.number + 1:03d}",
                "trial_number": trial.number,
                "parameters": parameters,
                "overrides": suggested,
                "mapped_overrides": mapped_overrides,
                "metrics": metrics,
                "score": score,
                "success": success,
                "error": result.get("error"),
            }
            candidate_results.append(payload)
            if success and (best_result is None or score > float(best_result["candidate"]["score"])):
                best_result = {"candidate": payload, "backtest": result}
            trial.set_user_attr("success", success)
            if result.get("error"):
                trial.set_user_attr("error", str(result["error"]))
            return score

        def report_progress(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
            completed = len(study.trials)
            if progress_callback:
                progress_callback(completed, max_trials, f"Optuna 参数优化进行中 {completed}/{max_trials} 组")

        try:
            study.optimize(evaluate, n_trials=max_trials, callbacks=[report_progress], catch=(Exception,))
        except Exception as exc:
            diagnostics.append(diagnostic("error", f"Optuna study failed: {exc}"))

        successful = [item for item in candidate_results if item["success"]]
        if not successful or best_result is None:
            return self._failure("all Optuna trials failed or were pruned", diagnostics, candidate_results)

        successful.sort(key=lambda item: float(item["score"]), reverse=True)
        rank_by_trial = {int(item["trial_number"]): rank for rank, item in enumerate(successful, start=1)}
        grid_summary = [
            {
                "rank": rank_by_trial.get(int(item["trial_number"]), 0),
                "label": item["label"],
                "trial_number": item["trial_number"],
                "parameters": item["overrides"],
                "score": item["score"],
                "sharpe": item["metrics"].get("sharpe"),
                "strategy_return": item["metrics"].get("strategy_return"),
                "benchmark_return": item["metrics"].get("benchmark_return"),
                "excess_return": item["metrics"].get("excess_return"),
                "success": item["success"],
                "error": item["error"],
            }
            for item in candidate_results
        ]
        grid_summary.sort(key=lambda item: (item["rank"] == 0, item["rank"] or 999999))
        diagnostics.append(diagnostic("info", f"Optuna selected {successful[0]['label']} from {len(study.trials)} trials"))
        return {
            "success": True,
            "recommended": dict(successful[0]),
            "candidates": candidate_results,
            "grid_summary": grid_summary,
            "best_result": best_result["backtest"],
            "diagnostics": diagnostics,
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": None,
        }

    def _failure(
        self,
        error: str,
        diagnostics: list[dict[str, Any]],
        candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "recommended": None,
            "candidates": list(candidates or []),
            "grid_summary": [],
            "best_result": None,
            "diagnostics": diagnostics + [diagnostic("error", error)],
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": error,
        }
