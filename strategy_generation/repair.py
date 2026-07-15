from __future__ import annotations

from typing import Any
import json
import re

from strategy_generation.providers import build_provider


REPAIR_SYSTEM_PROMPT = """You repair Python vn.py CTA strategy code for the GYRO_NICERT research platform.

Make only the minimum changes required for the supplied strategy to run normally on the platform.
Preserve the strategy class name, parameters, signal logic, entry rules, exit rules, and timing whenever possible.
Do not optimize performance, tune thresholds, add new features, or redesign the strategy.

Platform compatibility rules:
- The strategy class inherits CtaTemplate and remains a complete single-file strategy.
- The returned class name must be a valid Python identifier and the code must be directly usable for backtesting.
- Use fixed_size = 1 for orders. If use_dynamic_size exists, set it to 0.
- Keep order volume based on fixed_size instead of account capital or target notional.
- Market data is supplied through on_bar. Do not add network, RQData, database, or backtesting-engine calls.
- Do not invent missing trading logic. If an external dependency cannot be removed safely, keep the original logic and report a warning.

Status rules:
- status="runnable" only when the repaired strategy is self-contained and you judge it can run directly in the platform backtest. It must not depend on local files, schedule_path, CSV/Parquet files, external data, missing packages, imported strategy source, or hard-coded historical signals.
- status="warning" when you produced or partially repaired code but any local file, schedule_path, CSV/Parquet, external data, missing dependency, hard-coded historical signal, or incomplete repair remains. List every reason in reasons. Never use runnable when reasons is non-empty.
- status="failed" when no meaningful repair can be produced, required source is missing, or you explicitly judge the repair failed. Return an empty strategy_code and explain the failure in error.
- A launcher or runner that imports the real strategy from source code not included in the request is failed. Do not fabricate a replacement strategy.

Language rule:
- All human-facing text in changes, reasons, and error must be concise Simplified Chinese.
- Do not return English explanations, even when the original code or dependency names are English.

Return one JSON object only:
{
  "status": "runnable",
  "strategy_code": "complete repaired Python code",
  "changes": ["short change summary"],
  "reasons": [],
  "error": null
}
"""


def _strip_code_fence(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:python)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_response(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI repair response must be a JSON object")
    return payload


def _localized_items(values: Any, fallback: str) -> list[str]:
    items = [str(item).strip() for item in values or [] if str(item).strip()]
    return [item if re.search(r"[\u4e00-\u9fff]", item) else fallback for item in items]


def _localized_error(error: Any, fallback: str) -> str:
    text = str(error or "").strip()
    return text if re.search(r"[\u4e00-\u9fff]", text) else fallback


def _response_items(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"AI 返回格式错误：{name} 必须是列表")
    return value


def repair_strategy_code(
    *,
    strategy_name: str,
    strategy_code: str,
    vt_symbol: str = "",
    interval: str = "1m",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_code = str(strategy_code or "")
    if not source_code.strip():
        return {
            "status": "failed",
            "success": False,
            "can_backtest": False,
            "strategy_code": "",
            "changes": [],
            "reasons": ["策略代码为空"],
            "warnings": [],
            "blocking_issues": [],
            "error": "策略代码为空",
        }

    try:
        content = build_provider(options).complete(
            [
                {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Strategy name: {str(strategy_name or '').strip()}\n"
                        f"Symbol: {str(vt_symbol or '').strip()}\n"
                        f"Interval: {str(interval or '1m').strip()}\n\n"
                        "Original strategy code:\n"
                        f"<strategy_code>\n{source_code}\n</strategy_code>"
                    ),
                },
            ]
        )
        payload = _parse_response(content)
        status = str(payload.get("status") or "").strip().lower()
        changes = _localized_items(_response_items(payload, "changes"), "AI 已完成代码修正")
        reasons = _localized_items(
            [
                *_response_items(payload, "reasons"),
                *_response_items(payload, "warnings"),
                *_response_items(payload, "blocking_issues"),
            ],
            "AI 判断代码仍有需要人工处理的问题",
        )
        if payload.get("strategy_code") is not None and not isinstance(payload.get("strategy_code"), str):
            raise ValueError("AI 返回格式错误：strategy_code 必须是字符串")
        repaired_code = _strip_code_fence(str(payload.get("strategy_code") or ""))
        if status not in {"runnable", "warning", "failed"}:
            return {
                "status": "failed",
                "success": False,
                "can_backtest": False,
                "strategy_code": "",
                "changes": changes,
                "reasons": ["AI 返回格式错误，缺少有效的修正状态"],
                "warnings": [],
                "blocking_issues": [],
                "error": "AI 返回格式错误，缺少有效的修正状态",
            }
        if status == "runnable" and (not repaired_code or reasons or payload.get("can_backtest") is False):
            if not repaired_code:
                return {
                    "status": "failed",
                    "success": False,
                    "can_backtest": False,
                    "strategy_code": "",
                    "changes": changes,
                    "reasons": ["AI 修正没有返回可用代码"],
                    "warnings": [],
                    "blocking_issues": [],
                    "error": "AI 修正没有返回可用代码",
                }
            status = "warning"
            if not reasons:
                reasons = ["AI 未确认修正后的代码可以在平台独立运行"]
        if status == "warning":
            if not reasons:
                reasons = ["AI 判断代码仍需人工处理"]
            return {
                "status": "warning",
                "success": False,
                "can_backtest": False,
                "strategy_code": repaired_code,
                "changes": changes,
                "reasons": reasons,
                "warnings": reasons,
                "blocking_issues": [],
                "error": None,
            }
        if status == "failed":
            error = _localized_error(payload.get("error") or (reasons[0] if reasons else "AI 明确表示代码修正失败"), "AI 明确表示代码修正失败")
            return {
                "status": "failed",
                "success": False,
                "can_backtest": False,
                "strategy_code": "",
                "changes": changes,
                "reasons": reasons or [error],
                "warnings": [],
                "blocking_issues": reasons,
                "error": error,
            }
        return {
            "status": "runnable",
            "success": True,
            "can_backtest": True,
            "strategy_code": repaired_code,
            "changes": changes,
            "reasons": [],
            "warnings": [],
            "blocking_issues": [],
            "error": None,
        }
    except Exception as exc:
        error = _localized_error(exc, "AI 修正请求失败，请检查接口配置或网络后重试")
        return {
            "status": "failed",
            "success": False,
            "can_backtest": False,
            "strategy_code": "",
            "changes": [],
            "reasons": [error],
            "warnings": [],
            "blocking_issues": [],
            "error": error,
        }
