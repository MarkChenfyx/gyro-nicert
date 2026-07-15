from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from uuid import uuid4
import re

from common.time_utils import timestamp_id
from backend.core.hashing import compute_sha256
from backend.core.paths import GENERATED_STRATEGIES_ROOT
from backend.domain.enums import ArtifactType
from backend.repositories import artifact_repository, strategy_repository
from backend.services import natural_language_source_service
from strategy_generation.validation import validate_open_order_volumes


def _strategy_id() -> str:
    return f"strategy_{timestamp_id()}_{uuid4().hex[:6]}"


def _fallback_family(name: str) -> str:
    family = re.sub(r"\s+", "_", str(name or "").strip())
    family = re.sub(r'[<>:"/\\\\|?*]', "_", family)
    family = family.strip(" ._")
    return family or "strategy"


def _next_strategy_version(strategy_family: str) -> str:
    family_dir = GENERATED_STRATEGIES_ROOT / strategy_family
    version = timestamp_id()
    if not (family_dir / version).exists():
        return version
    suffix = 1
    while (family_dir / f"{version}_{suffix:02d}").exists():
        suffix += 1
    return f"{version}_{suffix:02d}"


def strategy_label(strategy_family: str, strategy_version: str) -> str:
    return f"{strategy_family} | {strategy_version}"


def extract_class_name_from_code(code: str) -> str:
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError as exc:
        line = getattr(exc, "lineno", None)
        detail = f"第 {line} 行附近" if line else "代码中"
        raise ValueError(f"{detail}存在 Python 语法错误: {exc.msg}") from exc
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            return node.name
    raise ValueError("代码里没有解析到可用的策略类名，请确认粘贴的是完整的 vnpy_ctastrategy 策略类。")


def _source_offset(lines: list[str], lineno: int, column: int) -> int:
    return sum(len(line) for line in lines[: max(0, lineno - 1)]) + column


def _fixed_size_assignment(class_node: ast.ClassDef) -> ast.AST | None:
    for node in class_node.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "fixed_size" for target in node.targets):
            return node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "fixed_size":
            return node
    return None


def normalize_fixed_size(code: str) -> tuple[str, bool, str]:
    """Return executable strategy code with the platform unit position enforced."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False, ""

    strategy_class = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and not node.name.startswith("_")),
        None,
    )
    if strategy_class is None:
        return code, False, ""

    assignment = _fixed_size_assignment(strategy_class)
    lines = code.splitlines(keepends=True)
    if assignment is not None:
        value = getattr(assignment, "value", None)
        if value is None or not hasattr(value, "lineno") or not hasattr(value, "end_lineno"):
            return code, False, ""
        start = _source_offset(lines, value.lineno, value.col_offset)
        end = _source_offset(lines, value.end_lineno, value.end_col_offset)
        current_value = code[start:end].strip()
        if current_value == "1":
            return code, False, "fixed_size is already normalized to 1"
        return (
            f"{code[:start]}1{code[end:]}",
            True,
            f"fixed_size was {current_value or 'unset'} and was normalized to 1 for unit-position research",
        )

    first_body = strategy_class.body[0] if strategy_class.body else None
    docstring = (
        first_body
        if isinstance(first_body, ast.Expr) and isinstance(getattr(first_body, "value", None), ast.Constant)
        and isinstance(first_body.value.value, str)
        else None
    )
    anchor_line = (
        (getattr(docstring, "end_lineno", None) + 1)
        if getattr(docstring, "end_lineno", None)
        else getattr(first_body, "lineno", None) or strategy_class.lineno + 1
    )
    indent = " " * ((getattr(first_body, "col_offset", strategy_class.col_offset + 4)) or strategy_class.col_offset + 4)
    insert_at = _source_offset(lines, anchor_line, 0)
    addition = f"{indent}fixed_size = 1\n"
    return (
        f"{code[:insert_at]}{addition}{code[insert_at:]}",
        True,
        "fixed_size was missing and was added as 1 for unit-position research",
    )


def _register_strategy(
    *,
    strategy_name: str,
    source_text: str,
    code: str,
    source_filename: str,
    source_type: str,
    strategy_family: str,
    class_name: str | None = None,
) -> dict[str, Any]:
    strategy_version = _next_strategy_version(strategy_family)
    strategy_id = _strategy_id()
    strategy_dir = GENERATED_STRATEGIES_ROOT / strategy_family / strategy_version
    strategy_dir.mkdir(parents=True, exist_ok=False)
    code_path = strategy_dir / "strategy.py"
    code_path.write_text(str(code or ""), encoding="utf-8")
    code_hash = compute_sha256(code_path)
    resolved_strategy_name = strategy_label(strategy_family, strategy_version)

    strategy = strategy_repository.create_strategy(
        strategy_id=strategy_id,
        strategy_name=resolved_strategy_name,
        strategy_family=strategy_family,
        strategy_version=strategy_version,
        source_filename=source_filename,
        source_type=source_type,
        source_text=source_text,
        class_name=str(class_name or "").strip() or None,
        code_path=str(code_path),
        code_hash=code_hash,
    )
    artifact_repository.create_artifact(
        owner_type="strategy",
        owner_id=strategy_id,
        artifact_type=ArtifactType.STRATEGY_CODE.value,
        path=str(code_path),
        sha256=code_hash,
    )
    return strategy


def register_generated_strategy(
    strategy_name: str,
    source_text: str,
    code: str,
    *,
    source_filename: str | None = None,
    class_name: str | None = None,
) -> dict[str, Any]:
    normalized_code, _, _ = normalize_fixed_size(str(code or ""))
    validate_open_order_volumes(normalized_code)
    resolved_filename = (
        natural_language_source_service.clean_source_filename(source_filename, append_txt=True)
        if source_filename
        else f"{_fallback_family(strategy_name)}.txt"
    )
    strategy_family = (
        natural_language_source_service.source_family_from_filename(resolved_filename)
        if source_filename
        else _fallback_family(strategy_name)
    )
    return _register_strategy(
        strategy_name=strategy_name,
        source_text=source_text,
        code=normalized_code,
        source_filename=resolved_filename,
        source_type="generated",
        strategy_family=strategy_family,
        class_name=class_name,
    )


def register_manual_strategy(
    strategy_name: str,
    code: str,
) -> dict[str, Any]:
    resolved_name = str(strategy_name or "").strip()
    if not resolved_name:
        raise ValueError("策略名称不能为空。")
    resolved_code = str(code or "")
    if not resolved_code.strip():
        raise ValueError("strategy.py 代码不能为空。")
    normalized_code, fixed_size_normalized, fixed_size_message = normalize_fixed_size(resolved_code)
    class_name = extract_class_name_from_code(normalized_code)
    validate_open_order_volumes(normalized_code)
    strategy_family = _fallback_family(resolved_name)
    source_filename = f"{strategy_family}.py"
    strategy = _register_strategy(
        strategy_name=resolved_name,
        source_text=resolved_code,
        code=normalized_code,
        source_filename=source_filename,
        source_type="manual_code",
        strategy_family=strategy_family,
        class_name=class_name,
    )
    return {
        **strategy,
        "fixed_size": 1,
        "fixed_size_normalized": fixed_size_normalized,
        "fixed_size_message": fixed_size_message,
    }
