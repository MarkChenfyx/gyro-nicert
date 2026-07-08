from __future__ import annotations

from itertools import product
from typing import Any
import json


def diagnostic(level: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"level": level, "message": message}
    payload.update(extra)
    return payload


def json_marker(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def dedupe(values: list[Any]) -> list[Any]:
    unique: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json_marker(value)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(value)
    return unique


def values_from_range(spec: Any, base_value: Any = None) -> list[Any]:
    if isinstance(spec, list):
        return dedupe(list(spec))
    if isinstance(spec, tuple):
        return dedupe(list(spec))
    if not isinstance(spec, dict):
        return [spec] if spec is not None else []
    if isinstance(spec.get("values"), list):
        return dedupe(list(spec["values"]))
    low = spec.get("low")
    high = spec.get("high")
    step = spec.get("step")
    if low in {None, ""} or high in {None, ""} or step in {None, ""}:
        return []
    value_type = str(spec.get("type") or ("int" if isinstance(base_value, int) and not isinstance(base_value, bool) else "float")).lower()
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
    return dedupe(values)


def candidate_grid(
    base_parameters: dict[str, Any],
    parameter_space: dict[str, Any],
    *,
    selected_parameters: list[str] | None = None,
    max_trials: int = 200,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    names = [str(name) for name in (selected_parameters or parameter_space.keys()) if str(name) in parameter_space]
    unknown = [str(name) for name in (selected_parameters or []) if str(name) not in parameter_space]
    if unknown:
        diagnostics.append(diagnostic("warning", f"ignored parameters without range: {', '.join(unknown)}"))
    value_grid = [
        (name, values_from_range(parameter_space[name], base_parameters.get(name)))
        for name in names
    ]
    value_grid = [(name, values) for name, values in value_grid if values]
    if not value_grid:
        return [], diagnostics
    total = 1
    for _, values in value_grid:
        total *= len(values)
    if total > max_trials:
        raise ValueError(f"Manual grid has too many combinations: {total}. Increase step size or reduce parameters. Limit={max_trials}.")
    candidate_rows: list[dict[str, Any]] = []
    names = [name for name, _values in value_grid]
    value_lists = [values for _name, values in value_grid]
    for index, values in enumerate(product(*value_lists), start=1):
        overrides = dict(zip(names, values, strict=False))
        candidate_rows.append(
            {
                "label": f"candidate_{index:03d}",
                "parameters": {**base_parameters, **overrides},
                "overrides": overrides,
            }
        )
    return candidate_rows, diagnostics


def metric_value(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
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


def score_metrics(metrics: dict[str, Any], objective: str) -> float:
    normalized = str(objective or "sharpe").strip().lower()
    if normalized in {"max_drawdown", "drawdown", "max_ddpercent"}:
        return -abs(metric_value(metrics, "drawdown", 0.0))
    return metric_value(metrics, normalized, metric_value(metrics, "sharpe", metric_value(metrics, "total_return", 0.0)))
