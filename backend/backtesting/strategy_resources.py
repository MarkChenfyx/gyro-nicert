"""Portable frozen-model attachments, carried by the existing run configuration."""
from __future__ import annotations

import ast
import base64
import hashlib
from pathlib import PurePosixPath, Path

MODEL_SUFFIXES = {".model", ".pkl", ".pickle", ".joblib", ".npy"}
MAX_BYTES = 16 * 1024 * 1024
KBINS_PARAMETERS = {"long_label", "short_label", "holding_window"}


def validate_resources(files: dict[str, str], code: str) -> dict[str, str]:
    """Validate names and payloads without deserializing uploaded models."""
    total = 0
    hashes = {}
    names = set()
    for name, encoded in files.items():
        path = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or ".." in path.parts or str(path) != name
                or path.suffix.lower() not in MODEL_SUFFIXES):
            raise ValueError(f"模型附件路径不支持：{name}")
        if name.casefold() in names:
            raise ValueError(f"模型附件重名：{name}")
        names.add(name.casefold())
        if len(encoded) > MAX_BYTES * 4 // 3 + 4:
            raise ValueError("模型附件合计不能超过16MB")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError(f"模型附件编码无效：{name}") from exc
        total += len(raw)
        if not raw or total > MAX_BYTES:
            raise ValueError("模型附件不能为空，且合计不能超过16MB")
        hashes[name] = hashlib.sha256(raw).hexdigest()
    # Support the existing flat selection + open('strategies/foo.model') convention.
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "open":
            continue
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            continue
        ref = PurePosixPath(arg.value.replace("\\", "/"))
        if ref.suffix.lower() not in MODEL_SUFFIXES:
            continue
        if ref.is_absolute() or ":" in str(ref) or ".." in ref.parts:
            raise ValueError("模型路径必须是策略包内相对路径")
        if str(ref) not in files and not (ref.parent == PurePosixPath("strategies") and ref.name in files):
            raise ValueError(f"缺少模型附件：{ref}")
    return hashes


def stage_resources(root: Path, files: dict[str, str], code: str) -> None:
    validate_resources(files, code)
    for name, encoded in files.items():
        raw = base64.b64decode(encoded, validate=True)
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if "/" not in name and f"strategies/{name}" not in files:
            target = root / "strategies" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)


def frozen_parameters(code: str) -> set[str]:
    # This first release recognizes the shipped KBins family only. Unknown
    # frozen models remain runnable, but have no automatically editable params.
    tree = ast.parse(code)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    return set(KBINS_PARAMETERS) if any(node.name.startswith("Kbins_") for node in classes) else set()
