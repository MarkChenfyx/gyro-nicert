from __future__ import annotations

from typing import Any


HIDDEN_EXACT_NAMES = {
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

HIDDEN_NAME_TOKENS = {
    "session_open",
    "session_close",
    "market_open",
    "market_close",
    "open_hour",
    "open_minute",
    "close_hour",
    "close_minute",
    "account",
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


def normalize_parameter_name(name: str) -> str:
    return str(name or "").strip().lower()


def infer_parameter_role(name: str, value: Any = None) -> str:
    normalized = normalize_parameter_name(name)
    if normalized in HIDDEN_EXACT_NAMES or normalized.endswith("_id") or normalized.endswith("_path"):
        if normalized == "account_id" or normalized.endswith("_id"):
            return "account_binding"
        if normalized in {"fixed_size", "position_pct"} or any(token in normalized for token in ["position", "size", "qty"]):
            return "position_sizing"
        return "system_fixed"
    if any(token in normalized for token in HIDDEN_NAME_TOKENS):
        return "market_session"
    if any(token in normalized for token in SAFETY_SWITCH_TOKENS):
        return "safety_switch"
    if any(token in normalized for token in ["position", "size", "qty"]):
        return "position_sizing"
    if any(token in normalized for token in ["duration", "window", "period", "length", "lookback", "bars", "bar_count"]):
        return "signal_window"
    if any(token in normalized for token in ["stop", "take_profit", "risk", "atr", "trail", "loss"]):
        return "risk_control"
    if any(token in normalized for token in ["threshold", "band", "ratio", "multiple", "multiplier", "buffer", "range", "z", "pct", "percent"]):
        return "signal_threshold"
    if any(token in normalized for token in ["entry", "exit", "confirm", "filter"]):
        return "entry_exit_control"
    if isinstance(value, bool) or any(token in normalized for token in BOOLEAN_TOKENS):
        return "binary_switch"
    return "generic_numeric"


def hidden_reason(name: str, value: Any = None) -> str | None:
    normalized = normalize_parameter_name(name)
    role = infer_parameter_role(name, value)
    if normalized in HIDDEN_EXACT_NAMES:
        return role
    if normalized.endswith("_id") or normalized.endswith("_path"):
        return role
    if any(token in normalized for token in HIDDEN_NAME_TOKENS):
        return role
    if role in {"position_sizing", "market_session", "system_fixed", "account_binding", "safety_switch"}:
        return role
    return None


def is_visible_parameter(name: str, value: Any = None) -> bool:
    return hidden_reason(name, value) is None


def is_tunable_parameter(name: str, value: Any = None) -> bool:
    if not is_visible_parameter(name, value):
        return False
    return isinstance(value, (int, float, bool)) and not isinstance(value, str)


def infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "int"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    return "float"


def default_range_for_parameter(name: str, value: Any) -> dict[str, Any] | None:
    if not is_tunable_parameter(name, value):
        return None
    normalized = normalize_parameter_name(name)
    if isinstance(value, bool):
        return {"low": 0, "high": 1, "step": 1, "type": "int"}
    numeric = float(value)
    if isinstance(value, int) and not isinstance(value, bool):
        if value in {0, 1} and any(token in normalized for token in BOOLEAN_TOKENS):
            return {"low": 0, "high": 1, "step": 1, "type": "int"}
        min_value = 1 if any(token in normalized for token in ["duration", "window", "period", "length", "lookback", "bars", "count"]) else 0
        step = max(1, int(round(abs(numeric) * 0.1)) or 1)
        low = max(min_value, int(round(numeric - step * 2)))
        high = max(low, int(round(numeric + step * 2)))
        return {"low": low, "high": high, "step": step, "type": "int"}
    step = max(abs(numeric) * 0.1, 0.01)
    if any(token in normalized for token in ["pct", "percent", "ratio", "threshold", "stop", "trail", "atr", "multiplier"]):
        low = max(0.0, numeric - step * 2)
    else:
        low = numeric - step * 2
    high = numeric + step * 2
    return {
        "low": round(low, 6),
        "high": round(max(high, low), 6),
        "step": round(step, 6),
        "type": "float",
    }
