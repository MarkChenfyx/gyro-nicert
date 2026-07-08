from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any
import ast
import json
import math

import backtesting


OPTIMIZER_NAME = "legacy_parameter_optimizer"
OPTIMIZER_VERSION = "phase6_legacy_adapter_v1"

FROZEN_EXACT_PARAMETER_NAMES = {
    "account_id",
    "fixed_size",
    "position_pct",
    "capital",
    "rate",
    "slippage",
    "size",
    "pricetick",
    "vt_symbol",
    "symbol",
    "exchange",
    "interval",
}
FROZEN_TIME_PARAMETER_NAMES = {
    "session_open_hour",
    "session_open_minute",
    "session_close_hour",
    "session_close_minute",
    "default_session_open_hour",
    "default_session_open_minute",
    "default_session_close_hour",
    "default_session_close_minute",
    "market_open_hour",
    "market_open_minute",
    "market_close_hour",
    "market_close_minute",
}
SAFETY_SWITCH_TOKENS = {
    "emergency",
    "force_flat",
    "intraday_only",
    "trade_limit",
    "no_overnight",
    "flatten",
}
BOOLEAN_TOKENS = {
    "enable",
    "enabled",
    "use_",
    "long_only",
    "short_only",
    "allow_long",
    "allow_short",
    "only",
    "switch",
    "flag",
}


def _diagnostic(level: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"level": level, "message": message}
    payload.update(extra)
    return payload


def _json_marker(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _dedupe(values: list[Any]) -> list[Any]:
    unique: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = _json_marker(value)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(value)
    return unique


def _normalized_parameter_name(name: str) -> str:
    return str(name or "").strip().lower()


def _is_frozen_system_parameter(name: str) -> bool:
    normalized = _normalized_parameter_name(name)
    if normalized in FROZEN_EXACT_PARAMETER_NAMES or normalized in FROZEN_TIME_PARAMETER_NAMES:
        return True
    return normalized.endswith("_id") or normalized.endswith("_path")


def _is_safety_switch_parameter(name: str) -> bool:
    normalized = _normalized_parameter_name(name)
    return any(token in normalized for token in SAFETY_SWITCH_TOKENS)


def _is_boolean_like_parameter(name: str, value: Any) -> bool:
    normalized = _normalized_parameter_name(name)
    if isinstance(value, bool):
        return True
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return any(token in normalized for token in BOOLEAN_TOKENS | SAFETY_SWITCH_TOKENS)
    return False


def _infer_parameter_role(name: str) -> str:
    normalized = _normalized_parameter_name(name)
    if _is_frozen_system_parameter(normalized):
        if normalized == "account_id" or normalized.endswith("_id"):
            return "account_binding"
        if normalized in FROZEN_TIME_PARAMETER_NAMES:
            return "market_session"
        return "system_fixed"
    if _is_safety_switch_parameter(normalized):
        return "safety_switch"
    if any(token in normalized for token in ["position", "size", "qty", "fixed_size"]):
        return "position_sizing"
    if any(token in normalized for token in ["duration", "window", "period", "length", "lookback", "bars", "bar_count"]):
        return "signal_window"
    if any(token in normalized for token in ["stop", "take_profit", "risk", "atr", "trail", "loss"]):
        return "risk_control"
    if any(token in normalized for token in ["threshold", "band", "ratio", "multiple", "multiplier", "buffer", "range", "z", "pct"]):
        return "signal_threshold"
    if any(token in normalized for token in ["hour", "minute", "session", "time", "close", "open"]):
        return "execution_timing"
    if any(token in normalized for token in ["entry", "exit", "confirm", "filter"]):
        return "entry_exit_control"
    if any(token in normalized for token in ["enable", "use_", "long_only", "short_only"]):
        return "binary_switch"
    return "generic_numeric"


def extract_declared_parameters_from_code(strategy_code: str) -> list[str]:
    if not str(strategy_code or "").strip():
        return []
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == "parameters":
                    if isinstance(statement.value, (ast.List, ast.Tuple)):
                        return [
                            item.value
                            for item in statement.value.elts
                            if isinstance(item, ast.Constant) and isinstance(item.value, str)
                        ]
    return []


def _build_search_values(name: str, value: Any) -> list[Any]:
    normalized = _normalized_parameter_name(name)
    if _is_frozen_system_parameter(normalized) or _is_safety_switch_parameter(normalized):
        return [value]
    if _is_boolean_like_parameter(normalized, value):
        return [False, True] if isinstance(value, bool) else [0, 1]
    if isinstance(value, int) and not isinstance(value, bool):
        if any(token in normalized for token in ["duration", "window", "period", "length", "lookback", "bars", "bar_count"]):
            candidates = [
                max(1, int(round(value * 0.3))),
                max(1, int(round(value * 0.5))),
                max(1, int(round(value * 0.75))),
                value,
                max(1, int(round(value * 1.25))),
                max(1, int(round(value * 1.5))),
                max(1, int(round(value * 2.0))),
                max(1, int(round(value * 2.5))),
            ]
        elif "hour" in normalized:
            candidates = [max(0, value - 1), value, min(23, value + 1)]
        elif "minute" in normalized:
            candidates = [max(0, value - 5), value, min(59, value + 5)]
        else:
            delta = max(1, int(round(abs(value) * 0.4)) or 1)
            candidates = [
                max(0, value - delta),
                max(0, int(round(value * 0.6))),
                max(0, int(round(value * 0.8))),
                value,
                int(round(value * 1.2)),
                int(round(value * 1.4)),
                value + delta,
            ]
        return _dedupe(candidates)
    if isinstance(value, float):
        if value == 0:
            return [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
        if "pct" in normalized:
            candidates = [
                max(0.0, round(value * 0.5, 6)),
                round(value * 0.6, 6),
                round(value * 0.8, 6),
                round(value, 6),
                round(value * 1.2, 6),
                round(value * 1.4, 6),
                max(0.0, round(value * 1.5, 6)),
            ]
        else:
            candidates = [
                round(value * 0.5, 6),
                round(value * 0.6, 6),
                round(value * 0.8, 6),
                round(value, 6),
                round(value * 1.2, 6),
                round(value * 1.4, 6),
                round(value * 1.5, 6),
            ]
        return _dedupe(candidates)
    return [value]


def _frange_values(low: Any, high: Any, step: Any, value_type: str) -> list[Any]:
    if low in {None, ""} or high in {None, ""} or step in {None, ""}:
        return []
    value_type = str(value_type or "float").lower()
    if value_type == "int":
        start = int(float(low))
        stop = int(float(high))
        stride = max(1, int(float(step)))
        if stop < start:
            start, stop = stop, start
        return list(range(start, stop + 1, stride))
    start = float(low)
    stop = float(high)
    stride = float(step)
    if stride <= 0:
        return []
    if stop < start:
        start, stop = stop, start
    values: list[float] = []
    current = start
    guard = 0
    while current <= stop + 1e-12 and guard < 10000:
        values.append(round(current, 10))
        current += stride
        guard += 1
    return values


def _values_from_space_spec(name: str, spec: Any, base_value: Any) -> list[Any]:
    if isinstance(spec, list):
        return _dedupe(spec)
    if isinstance(spec, tuple):
        return _dedupe(list(spec))
    if isinstance(spec, dict):
        if isinstance(spec.get("values"), list):
            return _dedupe(list(spec["values"]))
        if isinstance(spec.get("choices"), list):
            return _dedupe(list(spec["choices"]))
        value_type = str(spec.get("type") or ("int" if isinstance(base_value, int) and not isinstance(base_value, bool) else "float"))
        return _dedupe(_frange_values(spec.get("low"), spec.get("high"), spec.get("step"), value_type))
    return [spec] if spec is not None else []


def _filter_grid_values(name: str, values: list[Any]) -> list[Any]:
    normalized = _normalized_parameter_name(name)
    filtered = _dedupe(values)
    if normalized == "fixed_size":
        return [1]
    if any(token in normalized for token in ["window", "period", "length", "lookback", "bars"]):
        return [max(1, int(value)) for value in filtered if float(value) >= 1]
    if any(token in normalized for token in ["pct", "ratio"]):
        return [float(value) for value in filtered if float(value) >= 0]
    return filtered


def _build_parameter_inventory(strategy_code: str, base_parameters: dict[str, Any]) -> list[dict[str, Any]]:
    declared = extract_declared_parameters_from_code(strategy_code)
    ordered_names = list(dict.fromkeys([*declared, *base_parameters.keys()]))
    inventory: list[dict[str, Any]] = []
    for name in ordered_names:
        value = base_parameters.get(name)
        role = _infer_parameter_role(name)
        tunable = role not in {"account_binding", "position_sizing", "system_fixed", "market_session", "safety_switch"}
        if isinstance(value, str):
            tunable = False
        inventory.append(
            {
                "name": name,
                "value": value,
                "value_type": type(value).__name__,
                "role": role,
                "declared_in_strategy": name in declared,
                "tunable": tunable,
                "search_values": _build_search_values(name, value) if tunable else [value],
            }
        )
    return inventory


def _candidate_grid(
    base_parameters: dict[str, Any],
    parameter_space: dict[str, Any],
    inventory: list[dict[str, Any]],
    max_trials: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    tunable_by_name = {str(item["name"]): item for item in inventory if item.get("tunable")}
    if parameter_space:
        selected_names = [str(name) for name in parameter_space if str(name) in base_parameters]
        unknown_names = [str(name) for name in parameter_space if str(name) not in base_parameters]
        frozen_names = [name for name in selected_names if name not in tunable_by_name]
        if unknown_names:
            diagnostics.append(_diagnostic("warning", f"ignored unknown parameters: {', '.join(unknown_names)}"))
        if frozen_names:
            diagnostics.append(_diagnostic("warning", f"ignored frozen parameters: {', '.join(frozen_names)}"))
        value_grid = [
            (
                name,
                _filter_grid_values(name, _values_from_space_spec(name, parameter_space[name], base_parameters.get(name))),
            )
            for name in selected_names
            if name in tunable_by_name
        ]
    else:
        value_grid = [
            (str(item["name"]), _filter_grid_values(str(item["name"]), list(item.get("search_values") or [])))
            for item in inventory
            if item.get("tunable")
        ]
    value_grid = [(name, values) for name, values in value_grid if values]
    if not value_grid:
        return [{"label": "baseline", "parameters": dict(base_parameters), "overrides": {}}], diagnostics
    total = math.prod(len(values) for _, values in value_grid)
    if total > max_trials:
        diagnostics.append(_diagnostic("warning", f"candidate grid truncated from {total} to {max_trials} combinations"))
    names = [name for name, _ in value_grid]
    value_lists = [values for _, values in value_grid]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, values in enumerate(product(*value_lists), start=1):
        overrides = dict(zip(names, values, strict=False))
        parameters = {**base_parameters, **overrides}
        marker = _json_marker(parameters)
        if marker in seen:
            continue
        seen.add(marker)
        candidates.append({"label": f"candidate_{index:03d}", "parameters": parameters, "overrides": overrides})
        if len(candidates) >= max_trials:
            break
    if _json_marker(base_parameters) not in seen:
        candidates.insert(0, {"label": "baseline", "parameters": dict(base_parameters), "overrides": {}})
    return candidates, diagnostics


def _metric_value(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    aliases = {
        "sharpe": ["sharpe", "sharpe_ratio"],
        "sharpe_ratio": ["sharpe_ratio", "sharpe"],
        "return": ["total_return", "annual_return", "total_net_pnl"],
        "total_return": ["total_return", "annual_return", "total_net_pnl"],
        "annual_return": ["annual_return", "total_return"],
        "calmar": ["calmar", "return_drawdown_ratio"],
        "drawdown": ["max_drawdown", "max_ddpercent"],
    }
    for name in aliases.get(key, [key]):
        try:
            value = metrics.get(name)
            if value not in {None, ""}:
                return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)


def _score(metrics: dict[str, Any], objective: str) -> float:
    normalized = str(objective or "sharpe").strip().lower()
    if normalized in {"max_drawdown", "drawdown", "max_ddpercent"}:
        return -abs(_metric_value(metrics, "drawdown", 0.0))
    return _metric_value(metrics, normalized, _metric_value(metrics, "sharpe", _metric_value(metrics, "total_return", 0.0)))


@dataclass(slots=True)
class LegacyParameterOptimizer:
    optimizer_name: str = OPTIMIZER_NAME
    optimizer_version: str = OPTIMIZER_VERSION

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
        diagnostics: list[dict[str, Any]] = [_diagnostic("info", "legacy-style parameter optimizer adapter started")]
        if not str(strategy_code or "").strip():
            return self._failure("strategy_code is empty", diagnostics)
        if not str(class_name or "").strip():
            return self._failure("class_name is empty", diagnostics)
        if not str(vt_symbol or "").strip():
            return self._failure("vt_symbol is empty", diagnostics)

        parameters = dict(base_parameters or {})
        if "fixed_size" in parameters:
            parameters["fixed_size"] = 1
        inventory = _build_parameter_inventory(strategy_code, parameters)
        max_trials = max(1, int(options.get("max_trials") or backtest_config.get("max_trials") or 60))
        candidates, grid_diagnostics = _candidate_grid(parameters, dict(parameter_space or {}), inventory, max_trials=max_trials)
        diagnostics.extend(grid_diagnostics)
        candidate_results: list[dict[str, Any]] = []
        grid_summary: list[dict[str, Any]] = []

        for index, candidate in enumerate(candidates, start=1):
            result = backtesting.run_backtest(
                strategy_code=strategy_code,
                class_name=class_name,
                vt_symbol=vt_symbol,
                parameters=dict(candidate["parameters"]),
                config=dict(backtest_config or {}),
            )
            metrics = dict(result.get("metrics") or {})
            score = _score(metrics, objective) if result.get("success") else float("-inf")
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
            if result.get("diagnostics"):
                diagnostics.append(_diagnostic("info", f"candidate {index}/{len(candidates)} evaluated", label=candidate["label"]))

        successful = [candidate for candidate in candidate_results if candidate["success"]]
        if not successful:
            return {
                "success": False,
                "recommended": None,
                "candidates": candidate_results,
                "grid_summary": grid_summary,
                "diagnostics": diagnostics + [_diagnostic("error", "all parameter candidates failed")],
                "optimizer_name": self.optimizer_name,
                "optimizer_version": self.optimizer_version,
                "error": "all parameter candidates failed",
                "parameter_inventory": inventory,
            }

        successful.sort(key=lambda item: float(item.get("score", float("-inf"))), reverse=True)
        rank_by_label = {str(candidate["label"]): rank for rank, candidate in enumerate(successful, start=1)}
        for row in grid_summary:
            row["rank"] = rank_by_label.get(str(row["label"]), 0)
        grid_summary.sort(key=lambda item: (item["rank"] == 0, item["rank"] or 999999))
        recommended = dict(successful[0])
        diagnostics.append(_diagnostic("info", f"selected {recommended['label']} as recommended parameters"))
        return {
            "success": True,
            "recommended": recommended,
            "candidates": candidate_results,
            "grid_summary": grid_summary,
            "diagnostics": diagnostics,
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": None,
            "parameter_inventory": inventory,
        }

    def _failure(self, error: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "success": False,
            "recommended": None,
            "candidates": [],
            "grid_summary": [],
            "diagnostics": diagnostics + [_diagnostic("error", error)],
            "optimizer_name": self.optimizer_name,
            "optimizer_version": self.optimizer_version,
            "error": error,
            "parameter_inventory": [],
        }
