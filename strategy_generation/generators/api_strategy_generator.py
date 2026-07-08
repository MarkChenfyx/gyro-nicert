from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import ast
import json
import re

from strategy_generation.providers import build_provider


GENERATOR_NAME = "api_strategy_generator"
GENERATOR_VERSION = "phase6b_api_v1"
REQUIRED_KEYS = {
    "success",
    "source_text",
    "strategy_name",
    "class_name",
    "strategy_code",
    "params",
    "spec",
    "diagnostics",
    "generator_name",
    "generator_version",
    "error",
}

PROHIBITED_PATTERNS = {
    "rqdata access": r"\brqdatac\b|\bRQData\b",
    "database access": r"\bsqlite3\b|\bcreate_engine\b|\bSession\b|\bSELECT\b|\bINSERT\b",
    "file access": r"\bopen\s*\(|\.write_text\s*\(|\.write_bytes\s*\(",
    "network access": r"\brequests\b|\bhttpx\b|\burllib\b",
    "backtest access": r"\bBacktestingEngine\b|\brun_backtest\b|\bcalculate_result\b",
    "pandas or numpy": r"\bpandas\b|\bimport\s+pd\b|\bnumpy\b|\bimport\s+np\b",
}


def _diagnostic(stage: str, level: str, message: str) -> dict[str, str]:
    return {"stage": stage, "level": level, "message": message}


def _asset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets"


def _read_asset(relative_path: str) -> str:
    return (_asset_root() / relative_path).read_text(encoding="utf-8")


def _strip_code_fence(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:python|json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(value: str) -> dict[str, Any]:
    text = _strip_code_fence(value)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model response JSON must be an object")
    return payload


def _extract_class_name(strategy_code: str) -> str | None:
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return None
    public_classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef) and not node.name.startswith("_")]
    return public_classes[0] if public_classes else None


def _normalize_name(value: str, fallback: str = "Generated Strategy") -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:80] if text else fallback


@dataclass(slots=True)
class ApiStrategyGenerator:
    generator_name: str = GENERATOR_NAME
    generator_version: str = GENERATOR_VERSION

    def generate(self, source_text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = dict(options or {})
        diagnostics: list[dict[str, str]] = []
        source_text = str(source_text or "").strip()
        if not source_text:
            return self._failure(source_text=source_text, diagnostics=[_diagnostic("input", "error", "source_text is empty")], error="source_text is empty")

        try:
            messages = self._build_messages(source_text, options, diagnostics)
            content = build_provider(options).complete(messages)
            payload = _extract_json_object(content)
            result = self._normalize_payload(source_text, payload, diagnostics)
            errors = self._validate_result(result)
            if errors:
                diagnostics.extend(_diagnostic("validation", "error", item) for item in errors)
                return self._failure(
                    source_text=source_text,
                    diagnostics=diagnostics,
                    error="; ".join(errors),
                    strategy_name=result.get("strategy_name"),
                    class_name=result.get("class_name"),
                    strategy_code=result.get("strategy_code"),
                    params=result.get("params"),
                    spec=result.get("spec"),
                )
            diagnostics.append(_diagnostic("validation", "info", "api-generated strategy code validation passed"))
            result["diagnostics"] = diagnostics
            return result
        except Exception as exc:
            diagnostics.append(_diagnostic("generator", "error", str(exc)))
            return self._failure(source_text=source_text, diagnostics=diagnostics, error=str(exc))

    def _build_messages(self, source_text: str, options: dict[str, Any], diagnostics: list[dict[str, str]]) -> list[dict[str, str]]:
        prompt_template = str(options.get("prompt") or "").strip() or _read_asset("prompts/direct_codegen.md")
        template = _read_asset("templates/vnpy_cta_template.py")
        example = _read_asset("examples/han123_strategy_atr_hl.py")
        diagnostics.append(_diagnostic("prompt", "info", "loaded direct codegen prompt, vn.py template, and reference example"))
        rendered_prompt = (
            prompt_template
            .replace("{USER_REQUEST}", source_text)
            .replace("{PROJECT_RULES}", self._project_rules(template))
            .replace("{EXAMPLES}", example)
        )
        return [
            {"role": "system", "content": rendered_prompt},
            {"role": "user", "content": "严格按上面的 JSON 格式返回，不要输出 Markdown 或额外解释。"},
        ]

    def _project_rules(self, template: str) -> str:
        return (
            "当前项目使用 vn.py CTA BacktestingEngine，行情只通过 on_bar 的 BarData 输入。\n"
            "策略代码必须可以被动态加载并在本地 SQLite 行情回测中运行。\n"
            "建议导入：from vnpy_ctastrategy import CtaTemplate, StopOrder, TickData, BarData, TradeData, OrderData, BarGenerator, ArrayManager。\n"
            "如使用 Interval，单独导入：from vnpy.trader.constant import Interval。\n"
            "禁止访问 RQData、网络、文件、数据库、回测引擎、pandas、numpy。\n"
            "必须实现 __init__、on_init、on_start、on_stop、on_tick、on_bar；建议实现 on_order、on_trade、on_stop_order。\n"
            "on_tick 只做兼容或 BarGenerator 转发，核心交易逻辑放在 on_bar 或聚合后的 bar callback。\n"
            "下单数量必须来自 fixed_size，且 fixed_size >= 1。\n"
            "必须有入场、出场、止损或移动止损。不要生成无交易策略。\n\n"
            "vn.py CTA 模板参考：\n"
            f"{template}"
        )

    def _normalize_payload(self, source_text: str, payload: dict[str, Any], diagnostics: list[dict[str, str]]) -> dict[str, Any]:
        model_success = bool(payload.get("success", True))
        strategy_code = _strip_code_fence(str(payload.get("strategy_code") or ""))
        code_class_name = _extract_class_name(strategy_code) if strategy_code else None
        returned_class_name = str(payload.get("class_name") or "").strip() or None
        if code_class_name and returned_class_name and code_class_name != returned_class_name:
            diagnostics.append(_diagnostic("normalization", "warning", f"class_name mismatch, using code class {code_class_name}"))
        class_name = code_class_name or returned_class_name
        strategy_name = _normalize_name(str(payload.get("strategy_name") or class_name or ""), fallback="Generated Strategy")
        params = self._extract_params(payload)
        spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
        if not spec:
            spec = {
                "description": payload.get("description"),
                "strategy_type": payload.get("strategy_type"),
                "parameters": payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
            }
        for item in payload.get("diagnostics") or []:
            if isinstance(item, dict):
                diagnostics.append(_diagnostic(str(item.get("stage") or "model"), str(item.get("level") or "info"), str(item.get("message") or item)))
        error = None if model_success else str(payload.get("error") or "model reported generation failure")
        return {
            "success": model_success,
            "source_text": source_text,
            "strategy_name": strategy_name if model_success else payload.get("strategy_name"),
            "class_name": class_name,
            "strategy_code": strategy_code or None,
            "params": dict(params),
            "spec": dict(spec),
            "diagnostics": diagnostics,
            "generator_name": self.generator_name,
            "generator_version": self.generator_version,
            "error": error,
        }

    def _extract_params(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("params"), dict):
            return dict(payload["params"])
        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            return {}
        params: dict[str, Any] = {}
        for key, value in parameters.items():
            if isinstance(value, dict) and "default" in value:
                params[str(key)] = value["default"]
            else:
                params[str(key)] = value
        return params

    def _validate_result(self, result: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if set(result) != REQUIRED_KEYS:
            errors.append("generator result keys do not match required contract")
        if not bool(result.get("success")):
            errors.append(str(result.get("error") or "model reported generation failure"))
            return errors
        strategy_code = str(result.get("strategy_code") or "")
        if not strategy_code.strip():
            errors.append("strategy_code is empty")
            return errors
        try:
            tree = ast.parse(strategy_code)
        except SyntaxError as exc:
            errors.append(f"strategy_code syntax error: {exc}")
            return errors
        public_classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and not node.name.startswith("_")]
        if len(public_classes) != 1:
            errors.append("strategy_code must define exactly one public strategy class")
            return errors
        class_node = self._find_class(tree, str(result.get("class_name") or ""))
        if class_node is None:
            errors.append("strategy_code does not define the returned class_name")
            return errors
        if not self._inherits_cta_template(class_node):
            errors.append("strategy class must inherit CtaTemplate")
        missing = self._missing_required_members(class_node)
        errors.extend(f"strategy_code missing {item}" for item in missing)
        for label, pattern in PROHIBITED_PATTERNS.items():
            if re.search(pattern, strategy_code, flags=re.IGNORECASE):
                errors.append(f"strategy_code contains prohibited {label}")
        return errors

    def _find_class(self, tree: ast.Module, class_name: str) -> ast.ClassDef | None:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return node
        return None

    def _inherits_cta_template(self, class_node: ast.ClassDef) -> bool:
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id == "CtaTemplate":
                return True
            if isinstance(base, ast.Attribute) and base.attr == "CtaTemplate":
                return True
        return False

    def _missing_required_members(self, class_node: ast.ClassDef) -> list[str]:
        assigned = {target.id for node in class_node.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        methods = {node.name for node in class_node.body if isinstance(node, ast.FunctionDef)}
        required = ["parameters", "variables", "__init__", "on_init", "on_start", "on_stop", "on_tick", "on_bar"]
        missing: list[str] = []
        for item in required:
            if item == "__init__" or item.startswith("on_"):
                if item not in methods:
                    missing.append(item)
            elif item not in assigned:
                missing.append(item)
        return missing

    def _failure(
        self,
        *,
        source_text: str,
        diagnostics: list[dict[str, str]],
        error: str,
        strategy_name: str | None = None,
        class_name: str | None = None,
        strategy_code: str | None = None,
        params: dict[str, Any] | None = None,
        spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "source_text": source_text,
            "strategy_name": strategy_name,
            "class_name": class_name,
            "strategy_code": strategy_code,
            "params": dict(params or {}),
            "spec": dict(spec or {}),
            "diagnostics": diagnostics,
            "generator_name": self.generator_name,
            "generator_version": self.generator_version,
            "error": error,
        }
