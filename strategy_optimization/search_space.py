from __future__ import annotations

from pathlib import Path
from typing import Any
import ast
import json

from strategy_optimization import parameter_policy


def read_json_file(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    return json.loads(candidate.read_text(encoding="utf-8"))


def extract_class_name(strategy_code: str) -> str | None:
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            return node.name
    return None


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


def extract_class_defaults_from_code(strategy_code: str) -> dict[str, Any]:
    try:
        tree = ast.parse(strategy_code)
    except SyntaxError:
        return {}
    defaults: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            try:
                value = ast.literal_eval(statement.value)
            except Exception:
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    defaults[target.id] = value
        break
    return defaults


def params_from_generation_report(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    params = dict(report.get("params") or {})
    spec = dict(report.get("spec") or {})
    spec_parameters = dict(spec.get("parameters") or {})
    if not params and isinstance(report.get("parameters"), dict):
        for name, payload in dict(report["parameters"]).items():
            if isinstance(payload, dict) and "default" in payload:
                params[str(name)] = payload["default"]
            else:
                params[str(name)] = payload
        spec_parameters = dict(report.get("parameters") or {})
    return params, spec_parameters


def build_parameter_inventory(
    *,
    strategy_code: str,
    generation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = dict(generation_report or {})
    report_params, spec_parameters = params_from_generation_report(report)
    declared = extract_declared_parameters_from_code(strategy_code)
    class_defaults = extract_class_defaults_from_code(strategy_code)
    # A strategy class also contains runtime state such as ma_value, entry_price
    # and last_signal. Class attributes alone therefore do not make a parameter
    # tunable: only the vn.py ``parameters`` declaration and generation report
    # are authoritative parameter sources.
    names = list(dict.fromkeys([*declared, *report_params.keys()]))
    visible: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []

    for name in names:
        if name in {"parameters", "variables", "author"}:
            continue
        current = report_params.get(name, class_defaults.get(name))
        if current is None:
            diagnostics.append({"level": "warning", "message": f"ignored parameter without default value: {name}"})
            continue
        role = parameter_policy.infer_parameter_role(name, current)
        reason = parameter_policy.hidden_reason(name, current)
        description = ""
        if isinstance(spec_parameters.get(name), dict):
            description = str(spec_parameters[name].get("description") or "")
        if reason:
            hidden.append({"name": name, "current": current, "role": role, "reason": reason})
            continue
        range_spec = parameter_policy.default_range_for_parameter(name, current)
        if range_spec is None:
            hidden.append({"name": name, "current": current, "role": role, "reason": "not_numeric"})
            continue
        visible.append(
            {
                "name": name,
                "current": current,
                "role": role,
                "tunable": True,
                "description": description,
                **range_spec,
            }
        )
    return {
        "class_name": str(report.get("class_name") or extract_class_name(strategy_code) or ""),
        "base_parameters": {item["name"]: item["current"] for item in visible} | {
            item["name"]: item["current"] for item in hidden
        },
        "parameters": visible,
        "hidden_parameters": hidden,
        "declared_parameters": declared,
        "diagnostics": diagnostics,
    }
