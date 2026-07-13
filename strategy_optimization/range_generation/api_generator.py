from __future__ import annotations

from typing import Any
import json
import re

from strategy_generation.providers import build_provider
from strategy_optimization.range_generation.validator import validate_ai_search_space


SYSTEM_PROMPT = """你是量化策略参数分析器。只能分析输入中 declared_parameters 已声明的参数，不能添加真实策略参数。
输出单个 JSON 对象，字段必须为 parameters、constraints、virtual_parameters、warnings。
parameters 每项包含 name/category/optimize/type/low/high/step/scale/reason。
识别信号阈值、周期、风险参数和 warmup 参数；warmup、仓位、账户、成本、数据周期默认不优化。
constraints 使用简单比较表达式，例如 fast_window < slow_window，禁止函数和复杂表达式。
hour+minute 可以合并为 categorical 虚拟参数，choices 使用 HH:MM，maps_to 按 hour、minute 顺序列出。
范围应保守、包含默认值，避免仅根据参数名称机械扩大。只输出 JSON。"""


def _extract_json(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI search-space response must be a JSON object")
    return payload


def suggest_search_space(
    *,
    strategy_code: str,
    inventory: dict[str, Any],
    context: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    provider: Any = None,
) -> dict[str, Any]:
    static_parameters = list(inventory.get("parameters") or [])
    static_result = {
        "source": "static",
        "fallback_used": True,
        "parameters": static_parameters,
        "excluded_parameters": list(inventory.get("hidden_parameters") or []),
        "constraints": [],
        "virtual_parameters": [],
        "warnings": [],
        "diagnostics": [],
    }
    request_payload = {
        "strategy_code": strategy_code,
        "declared_parameters": {
            item["name"]: {"type": item.get("type"), "default": item.get("current"), "role": item.get("role"), "platform_hidden": False}
            for item in static_parameters
        } | {
            item["name"]: {"type": type(item.get("current")).__name__, "default": item.get("current"), "role": item.get("role"), "platform_hidden": True}
            for item in inventory.get("hidden_parameters") or []
        },
        "context": dict(context or {}),
    }
    try:
        client = provider or build_provider(options)
        content = client.complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(request_payload, ensure_ascii=False, default=str)},
        ])
        validated = validate_ai_search_space(_extract_json(content), inventory)
        if not validated["parameters"] and not validated["virtual_parameters"]:
            raise ValueError("AI did not return any valid optimization parameters")
        return {"source": "ai", "fallback_used": False, **validated}
    except Exception as exc:
        static_result["diagnostics"] = [{"level": "warning", "message": f"AI 建议不可用，已回退静态范围：{exc}"}]
        return static_result
