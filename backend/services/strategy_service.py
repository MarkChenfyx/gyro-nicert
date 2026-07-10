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
        code=code,
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
    class_name = extract_class_name_from_code(resolved_code)
    strategy_family = _fallback_family(resolved_name)
    source_filename = f"{strategy_family}.py"
    return _register_strategy(
        strategy_name=resolved_name,
        source_text=resolved_code,
        code=resolved_code,
        source_filename=source_filename,
        source_type="manual_code",
        strategy_family=strategy_family,
        class_name=class_name,
    )
