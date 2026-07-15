from __future__ import annotations

import ast


OPEN_ORDER_METHODS = {"buy", "short"}


def _is_self_fixed_size(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "fixed_size"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _open_order_volume(call: ast.Call) -> ast.AST | None:
    if len(call.args) >= 2:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "volume":
            return keyword.value
    return None


def validate_open_order_volumes(code: str) -> None:
    """Require every self.buy/self.short opening volume to be exactly self.fixed_size."""
    try:
        tree = ast.parse(str(code or ""))
    except SyntaxError as exc:
        line = getattr(exc, "lineno", None)
        detail = f"第 {line} 行附近" if line else "代码中"
        raise ValueError(f"{detail}存在 Python 语法错误: {exc.msg}") from exc

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr in OPEN_ORDER_METHODS
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            continue

        volume = _open_order_volume(node)
        if _is_self_fixed_size(volume):
            continue
        actual = ast.unparse(volume) if volume is not None else "未提供 volume"
        violations.append(f"第 {getattr(node, 'lineno', '?')} 行 self.{func.attr} 的开仓数量为 {actual}")

    if violations:
        raise ValueError(
            "开仓数量校验失败：buy 和 short 的开仓数量必须严格使用 self.fixed_size；"
            + "；".join(violations)
        )
