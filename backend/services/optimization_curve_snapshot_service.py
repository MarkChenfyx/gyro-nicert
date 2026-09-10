from __future__ import annotations

from backend.core.paths import path_fields

from pathlib import Path
from typing import Any
from uuid import uuid4
import csv
import json
import re
import shutil

from backend.common.time_utils import now_iso, timestamp_id
from backend.core.paths import OPTIMIZATION_CURVE_SNAPSHOTS_ROOT
from backend.repositories import run_repository, variant_repository


CURVE_FIELDS = ("date", "close_price", "pre_close", "net_pnl")
SNAPSHOT_ID_PATTERN = re.compile(r"curve_[0-9]{8}_[0-9]{6}_[a-f0-9]{6}")


def _clean_name(value: str, fallback: str = "优化曲线") -> str:
    name = " ".join(str(value or "").split()).strip()
    return (name or fallback)[:48]


def _snapshot_dir(snapshot_id: str) -> Path:
    if not SNAPSHOT_ID_PATTERN.fullmatch(str(snapshot_id or "")):
        raise ValueError(f"Invalid curve snapshot id: {snapshot_id}")
    root = OPTIMIZATION_CURVE_SNAPSHOTS_ROOT.resolve()
    path = (root / snapshot_id).resolve()
    if root not in path.parents:
        raise ValueError("Curve snapshot path is outside snapshot storage")
    return path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.tmp_{uuid4().hex[:8]}")
    staging.write_text(json.dumps(path_fields(payload, storing=True), ensure_ascii=False, indent=2), encoding="utf-8")
    staging.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return path_fields(json.loads(path.read_text(encoding="utf-8")))


def _read_curve(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_compact_curve(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f"{destination.name}.tmp_{uuid4().hex[:8]}")
    count = 0
    with source.open("r", encoding="utf-8-sig", newline="") as input_handle, staging.open(
        "w", encoding="utf-8", newline=""
    ) as output_handle:
        reader = csv.DictReader(input_handle)
        writer = csv.DictWriter(output_handle, fieldnames=list(CURVE_FIELDS))
        writer.writeheader()
        for row in reader:
            if not str(row.get("date") or "").strip():
                continue
            writer.writerow({field: row.get(field, "") for field in CURVE_FIELDS})
            count += 1
    if count <= 0:
        staging.unlink(missing_ok=True)
        raise ValueError("当前优化结果没有可保留的收益曲线")
    staging.replace(destination)
    return count


def _snapshot_payload(snapshot_dir: Path) -> dict[str, Any]:
    metadata_path = snapshot_dir / "metadata.json"
    curve_path = snapshot_dir / "curve.csv"
    if not metadata_path.exists() or not curve_path.exists():
        raise FileNotFoundError(f"Curve snapshot is incomplete: {snapshot_dir.name}")
    return {**_read_json(metadata_path), "curve": _read_curve(curve_path)}


def list_curve_snapshots() -> list[dict[str, Any]]:
    root = OPTIMIZATION_CURVE_SNAPSHOTS_ROOT
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in root.iterdir():
        if not path.is_dir() or not SNAPSHOT_ID_PATTERN.fullmatch(path.name):
            continue
        try:
            items.append(_snapshot_payload(path))
        except (FileNotFoundError, json.JSONDecodeError, csv.Error):
            continue
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def create_curve_snapshot(run_id: str, variant_name: str, name: str = "") -> dict[str, Any]:
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"未找到运行记录：{run_id}")
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"未找到优化版本：{variant_name}")

    run_path = Path(str(run.get("runtime_path") or "")).resolve()
    stored_curve_path = str(variant.get("daily_results_path") or "").strip()
    source_curve = Path(stored_curve_path).resolve() if stored_curve_path else (run_path / "variants" / variant_name / "daily_results.csv").resolve()
    if run_path not in source_curve.parents or not source_curve.exists() or not source_curve.is_file():
        raise FileNotFoundError("当前优化结果没有可保留的收益曲线")

    result: dict[str, Any] = {}
    result_path_value = str(variant.get("result_path") or "").strip()
    if not result_path_value:
        result_path_value = str(run_path / "variants" / variant_name / "result.json")
    if result_path_value:
        result_path = Path(result_path_value).resolve()
        if run_path in result_path.parents and result_path.exists() and result_path.is_file():
            result = _read_json(result_path)
    recommended = result.get("recommended") if isinstance(result.get("recommended"), dict) else {}
    metrics = recommended.get("metrics") if isinstance(recommended.get("metrics"), dict) else result.get("metrics") or {}
    parameters = recommended.get("parameters") if isinstance(recommended.get("parameters"), dict) else result.get("base_parameters") or {}

    snapshot_id = f"curve_{timestamp_id()}_{uuid4().hex[:6]}"
    snapshot_dir = _snapshot_dir(snapshot_id)
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    try:
        row_count = _write_compact_curve(source_curve, snapshot_dir / "curve.csv")
        metadata = {
            "snapshot_id": snapshot_id,
            "name": _clean_name(name, f"{variant_name} {timestamp_id()}"),
            "source_run_id": str(run_id),
            "source_variant_name": str(variant_name),
            "strategy_name": str(run.get("strategy_name") or ""),
            "vt_symbol": str(run.get("vt_symbol") or ""),
            "objective": result.get("objective"),
            "parameters": parameters,
            "metrics": {
                key: metrics.get(key)
                for key in ("sharpe", "sharpe_ratio", "excess_return", "strategy_return", "max_drawdown_value")
                if metrics.get(key) is not None
            },
            "row_count": row_count,
            "created_at": now_iso(),
        }
        _write_json_atomic(snapshot_dir / "metadata.json", metadata)
        return {**metadata, "curve": _read_curve(snapshot_dir / "curve.csv")}
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def rename_curve_snapshot(snapshot_id: str, name: str) -> dict[str, Any]:
    snapshot_dir = _snapshot_dir(snapshot_id)
    metadata_path = snapshot_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"未找到保留曲线：{snapshot_id}")
    metadata = _read_json(metadata_path)
    metadata["name"] = _clean_name(name)
    _write_json_atomic(metadata_path, metadata)
    return _snapshot_payload(snapshot_dir)


def delete_curve_snapshot(snapshot_id: str) -> None:
    snapshot_dir = _snapshot_dir(snapshot_id)
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"未找到保留曲线：{snapshot_id}")
    shutil.rmtree(snapshot_dir)
