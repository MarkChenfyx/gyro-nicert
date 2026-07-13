from __future__ import annotations

from math import isfinite
from typing import Any
import re

from strategy_optimization.parameter_policy import hidden_reason


DENYLIST = {
    "fixed_size", "account_id", "capital", "rate", "slippage", "size",
    "pricetick", "vt_symbol", "symbol", "exchange", "interval", "bar_window",
}
CONSTRAINT_RE = re.compile(r"^([A-Za-z_]\w*)\s*(<=|>=|<|>|==)\s*([A-Za-z_]\w*|-?\d+(?:\.\d+)?)$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _normalize_numeric(item: dict[str, Any], static: dict[str, Any]) -> dict[str, Any] | None:
    value_type = str(static.get("type") or "float")
    low = _number(item.get("low"))
    high = _number(item.get("high"))
    step = _number(item.get("step"))
    if low is None or high is None or low >= high or step is None or step <= 0:
        return None
    current = _number(static.get("current"))
    if current is not None:
        # Keep the current strategy as a valid baseline candidate.
        low, high = min(low, current), max(high, current)
        # AI suggestions are proposals, not authority. Keep ordinary ranges
        # within ±50% of the declared default to avoid accidental explosions.
        if current != 0:
            radius = abs(current) * 0.5
            low, high = max(low, current - radius), min(high, current + radius)
    name = str(static.get("name") or "").lower()
    if any(token in name for token in ("window", "period", "length", "lookback", "bars")):
        low = max(2, low)
    if any(token in name for token in ("_pct", "percent", "probability")) and current is not None and abs(current) <= 1:
        low, high = max(0.0, low), min(1.0, high)
    if value_type == "int":
        low, high, step = int(round(low)), int(round(high)), max(1, int(round(step)))
        if low >= high:
            return None
    count = int((high - low) / step) + 1
    if count > 1000:
        step = max(step, (high - low) / 999)
        if value_type == "int":
            step = max(1, int(round(step)))
    return {
        **static,
        "category": str(item.get("category") or static.get("role") or "generic_numeric"),
        "optimize": bool(item.get("optimize", True)),
        "low": low,
        "high": high,
        "step": step,
        "type": value_type,
        "scale": "log" if str(item.get("scale") or "").lower() == "log" and low > 0 else "linear",
        "reason": str(item.get("reason") or "AI 建议范围"),
    }


def validate_ai_search_space(ai_space: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    visible = {str(item["name"]): dict(item) for item in inventory.get("parameters") or []}
    hidden = {str(item["name"]): dict(item) for item in inventory.get("hidden_parameters") or []}
    declared = {**visible, **hidden}
    diagnostics: list[dict[str, str]] = []
    returned = {
        str(item.get("name")): item
        for item in ai_space.get("parameters") or []
        if isinstance(item, dict) and str(item.get("name") or "")
    }
    parameters: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for name, static in visible.items():
        item = returned.get(name)
        if item is None:
            parameters.append({**static, "category": static.get("role"), "optimize": True, "scale": "linear", "reason": "AI 未返回该参数，保留静态建议"})
            continue
        if item.get("optimize") is False:
            excluded.append({
                **static,
                "category": str(item.get("category") or static.get("role") or "generic_numeric"),
                "optimize": False,
                "scale": "linear",
                "reason": str(item.get("reason") or "AI 建议不优化"),
            })
            continue
        normalized = _normalize_numeric(item, static)
        if normalized is None:
            diagnostics.append({"level": "warning", "message": f"{name} 的 AI 范围无效，已恢复静态范围"})
            normalized = {**static, "category": static.get("role"), "optimize": True, "scale": "linear", "reason": "AI 范围无效，使用静态建议"}
        if not normalized["optimize"]:
            excluded.append(normalized)
        else:
            parameters.append(normalized)

    for name in returned:
        if name not in declared:
            diagnostics.append({"level": "warning", "message": f"忽略 AI 凭空添加的参数：{name}"})
        elif name in DENYLIST or hidden_reason(name, declared[name].get("current")):
            excluded.append({**declared[name], "optimize": False, "reason": "平台安全策略禁止优化"})

    virtual_parameters: list[dict[str, Any]] = []
    for item in ai_space.get("virtual_parameters") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        maps_to = [str(value) for value in item.get("maps_to") or []]
        choices = [str(value) for value in item.get("choices") or []]
        if not name or len(maps_to) != 2 or any(target not in declared or target in DENYLIST for target in maps_to):
            continue
        if not (maps_to[0].endswith("_hour") and maps_to[1].endswith("_minute")):
            continue
        choices = list(dict.fromkeys(choice for choice in choices if TIME_RE.match(choice)))
        if not choices:
            continue
        virtual_parameters.append({
            "name": name,
            "type": "categorical",
            "choices": choices,
            "maps_to": maps_to,
            "optimize": bool(item.get("optimize", True)),
            "category": "market_session",
            "reason": str(item.get("reason") or "将小时和分钟作为一个时间参数优化"),
        })

    allowed_names = set(declared) | {item["name"] for item in virtual_parameters}
    constraints: list[dict[str, str]] = []
    for item in ai_space.get("constraints") or []:
        expression = str(item.get("expression") or "") if isinstance(item, dict) else ""
        match = CONSTRAINT_RE.match(expression.strip())
        if not match:
            continue
        left, operator, right = match.groups()
        if left not in allowed_names or (right[0].isalpha() or right[0] == "_") and right not in allowed_names:
            continue
        constraints.append({"left": left, "operator": operator, "right": right, "type": "hard", "expression": expression})

    return {
        "parameters": parameters,
        "excluded_parameters": excluded,
        "constraints": constraints,
        "virtual_parameters": virtual_parameters,
        "warnings": [str(value) for value in ai_space.get("warnings") or []],
        "diagnostics": diagnostics,
    }
