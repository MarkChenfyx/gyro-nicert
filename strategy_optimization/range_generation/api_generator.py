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

核心要求：
1. 以“便于分组优化”为目标，不要一次把太多参数都设为 optimize=true。
2. 必须主动估算 optimize=true 参数形成的笛卡尔积总组数，尽量控制在 100 组以内；宁可少选参数、缩窄范围，也不要超过 100 组。
3. 如果候选参数很多，优先只启用 2-4 个最关键、最强相关、最值得先联调的参数；其余参数可以先设为 optimize=false。
4. 对于本轮不建议优化的参数，必须在 reason 里明确写出“建议后续单独优化”或“建议作为下一组参数继续优化”，让用户知道后续还能分组继续做。
5. 对于本轮启用优化的参数，也要在 reason 里解释为什么先优化这一组、它与哪些参数形成当前优先组。
6. 范围必须保守、包含默认值，避免仅根据参数名称机械扩大。
7. warnings 中可以补充分组建议，例如“第一组先做阈值+周期，第二组再做止损+止盈”。

只输出 JSON，不要输出解释性正文。"""


SYSTEM_PROMPT += """

第一轮探索范围规则（优先级高于上面的保守范围建议）：
1. 这是第一轮粗粒度探索，范围应尽可能宽，覆盖明显偏小、默认值附近和明显偏大的参数区域；不要只在默认值附近做小幅微调。
2. 必须包含默认值，但不要为了控制组合数而缩窄 low/high。优先扩大上下界，再使用更粗的 step 控制候选数量。
3. optimize=true 参数形成的笛卡尔积目标为约 50 组，建议控制在 40～60 组，最多不要超过 70 组。
4. 两个参数可优先安排为约 7×7；三个参数可安排为约 4×4×3 或 5×5×2。参数更多时减少 optimize=true 的数量，不要压缩每个关键参数的探索跨度。
5. 周期、窗口、阈值、倍数类参数应给出有区分度的宽范围；只要业务含义合法，第一轮出现较粗的步长是可以接受的。
6. reason 中简要说明这是第一轮宽范围探索，以及为何选择该跨度和步长。
"""


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
