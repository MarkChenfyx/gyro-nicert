from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import ast
import re


GENERATOR_NAME = "legacy_agent_generator"
GENERATOR_VERSION = "phase3_minimal_v1"


def _diagnostic(stage: str, level: str, message: str) -> dict[str, str]:
    return {"stage": stage, "level": level, "message": message}


def _normalize_name(value: str, fallback: str = "Generated Strategy") -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:80] if text else fallback


def _class_name_from_text(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        words = ["Generated", "Strategy"]
    if words[-1].lower() != "strategy":
        words.append("Strategy")
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if not name[0].isalpha():
        name = f"Generated{name}"
    return name


def _extract_class_name(strategy_code: str) -> str | None:
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            return node.name
    return None


@dataclass(slots=True)
class LegacyAgentGenerator:
    """Minimal adapter-shaped generator; no DB, tasks, backtests, or old outputs."""

    generator_name: str = GENERATOR_NAME
    generator_version: str = GENERATOR_VERSION

    def generate(self, source_text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = dict(options or {})
        diagnostics: list[dict[str, str]] = []
        source_text = str(source_text or "").strip()
        if not source_text:
            return self._failure(
                source_text=source_text,
                diagnostics=[_diagnostic("input", "error", "source_text is empty")],
                error="source_text is empty",
            )

        try:
            preprocessed = self._preprocess(source_text, diagnostics)
            spec = self._build_spec(preprocessed, options, diagnostics)
            strategy_code, params = self._generate_code(spec, diagnostics)
            class_name = _extract_class_name(strategy_code)
            validation_errors = self._validate_code(strategy_code, class_name)
            if validation_errors:
                diagnostics.extend(_diagnostic("validation", "error", item) for item in validation_errors)
                return self._failure(
                    source_text=source_text,
                    diagnostics=diagnostics,
                    error="; ".join(validation_errors),
                    spec=spec,
                    strategy_code=strategy_code,
                    params=params,
                    strategy_name=spec.get("strategy_name"),
                    class_name=class_name,
                )
            diagnostics.append(_diagnostic("validation", "info", "basic strategy code validation passed"))
            return {
                "success": True,
                "source_text": source_text,
                "strategy_name": spec["strategy_name"],
                "class_name": class_name,
                "strategy_code": strategy_code,
                "params": params,
                "spec": spec,
                "diagnostics": diagnostics,
                "generator_name": self.generator_name,
                "generator_version": self.generator_version,
                "error": None,
            }
        except Exception as exc:
            diagnostics.append(_diagnostic("generator", "error", str(exc)))
            return self._failure(source_text=source_text, diagnostics=diagnostics, error=str(exc))

    def _preprocess(self, source_text: str, diagnostics: list[dict[str, str]]) -> str:
        preprocessed = " ".join(source_text.split())
        diagnostics.append(_diagnostic("preprocess", "info", "normalized whitespace"))
        return preprocessed

    def _build_spec(self, preprocessed_text: str, options: dict[str, Any], diagnostics: list[dict[str, str]]) -> dict[str, Any]:
        strategy_name = _normalize_name(str(options.get("strategy_name") or ""), fallback="")
        if not strategy_name:
            strategy_name = _normalize_name(preprocessed_text, fallback="Generated Strategy")
        class_name = _class_name_from_text(str(options.get("class_name") or strategy_name))
        spec = {
            "schema": "strategy_generation.strategy_spec.v1",
            "strategy_name": strategy_name,
            "class_name": class_name,
            "source_summary": preprocessed_text[:240],
            "execution_timeframe": str(options.get("execution_timeframe") or "1m"),
            "parameters": {"fixed_size": 1, "fast_window": 10, "slow_window": 30},
        }
        diagnostics.append(_diagnostic("spec", "info", "built minimal strategy spec"))
        return spec

    def _generate_code(self, spec: dict[str, Any], diagnostics: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        class_name = str(spec["class_name"])
        params = dict(spec.get("parameters") or {})
        code = f'''from __future__ import annotations

try:
    from vnpy_ctastrategy import CtaTemplate
except Exception:
    class CtaTemplate:
        def __init__(self, *args, **kwargs):
            pass


class {class_name}(CtaTemplate):
    author = "gyro_nicert"

    fixed_size = {int(params.get("fixed_size", 1))}
    fast_window = {int(params.get("fast_window", 10))}
    slow_window = {int(params.get("slow_window", 30))}

    parameters = ["fixed_size", "fast_window", "slow_window"]
    variables = []

    def __init__(self, cta_engine=None, strategy_name="", vt_symbol="", setting=None):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting or {{}})

    def on_init(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_tick(self, tick):
        pass

    def on_bar(self, bar):
        pass
'''
        diagnostics.append(_diagnostic("codegen", "info", "generated minimal CTA-compatible strategy code"))
        return code, params

    def _validate_code(self, strategy_code: str, class_name: str | None) -> list[str]:
        errors: list[str] = []
        if not strategy_code.strip():
            errors.append("strategy_code is empty")
        try:
            ast.parse(strategy_code)
        except SyntaxError as exc:
            errors.append(f"strategy_code syntax error: {exc}")
        if not class_name:
            errors.append("strategy_code does not define a class")
        if "parameters" not in strategy_code:
            errors.append("strategy_code does not define parameters")
        return errors

    def _failure(
        self,
        *,
        source_text: str,
        diagnostics: list[dict[str, str]],
        error: str,
        spec: dict[str, Any] | None = None,
        strategy_code: str | None = None,
        params: dict[str, Any] | None = None,
        strategy_name: str | None = None,
        class_name: str | None = None,
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
