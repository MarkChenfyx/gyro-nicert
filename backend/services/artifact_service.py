from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4
import csv
import json
import shutil

from common.time_utils import now_iso, timestamp_id
from backend.core.hashing import compute_sha256
from backend.core.paths import POOL_STRATEGIES_ROOT, RUNS_ROOT


def _now() -> str:
    return now_iso()


def _stamp_id(prefix: str) -> str:
    return f"{prefix}_{timestamp_id()}_{uuid4().hex[:6]}"


def _run_path(run_id: str) -> Path:
    return RUNS_ROOT / str(run_id)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _records_from_rows(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    to_dict = getattr(rows, "to_dict", None)
    if callable(to_dict):
        return [dict(row) for row in to_dict(orient="records")]
    if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes, dict)):
        return [dict(row) for row in rows]
    raise TypeError("Rows must be a list[dict] or pandas DataFrame")


def _write_csv(path: Path, rows: Any) -> Path:
    records = _records_from_rows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for record in records:
        for key in record:
            if str(key) not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow({field: record.get(field, "") for field in fieldnames})
        else:
            handle.write("")
    return path


def _copy_required(source: Path, destination: Path, label: str) -> Path:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Missing required {label}: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _copy_optional(source: Path, destination: Path) -> Path | None:
    if not source.exists() or not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def create_run_artifact(run_type: str, strategy: dict[str, Any], source: str) -> dict[str, Any]:
    run_id = _stamp_id("run")
    run_path = _run_path(run_id)
    run_path.mkdir(parents=True, exist_ok=False)
    manifest_path = run_path / "manifest.json"
    manifest = {
        "schema": "gyro_nicert.run_manifest.v1",
        "run_id": run_id,
        "run_type": str(run_type),
        "strategy_id": str(strategy.get("strategy_id") or ""),
        "strategy_name": str(strategy.get("strategy_name") or ""),
        "strategy_family": str(strategy.get("strategy_family") or ""),
        "strategy_version": str(strategy.get("strategy_version") or ""),
        "source_filename": str(strategy.get("source_filename") or ""),
        "class_name": str(strategy.get("class_name") or ""),
        "source": str(source),
        "run_path": str(run_path),
        "created_at": _now(),
    }
    _write_json(manifest_path, manifest)
    return {
        "run_id": run_id,
        "run_path": run_path,
        "manifest_path": manifest_path,
    }


def save_run_input(run_id: str, input_payload: dict[str, Any]) -> Path:
    return _write_json(_run_path(run_id) / "input.json", input_payload)


def save_run_config(run_id: str, config_payload: dict[str, Any]) -> Path:
    return _write_json(_run_path(run_id) / "config.json", config_payload)


def save_strategy_code_to_run(run_id: str, code: str) -> Path:
    path = _run_path(run_id) / "strategy.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(code or ""), encoding="utf-8")
    return path


def save_variant_result(
    run_id: str,
    variant_name: str,
    result_payload: dict[str, Any],
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Path | None]:
    variant_dir = _run_path(run_id) / "variants" / str(variant_name)
    variant_dir.mkdir(parents=True, exist_ok=True)
    result_path = _write_json(variant_dir / "result.json", result_payload)
    daily_results_path = _write_csv(variant_dir / "daily_results.csv", daily_results) if daily_results is not None else None
    trades_path = _write_csv(variant_dir / "trades.csv", trades) if trades is not None else None
    return {
        "result_path": result_path,
        "daily_results_path": daily_results_path,
        "trades_path": trades_path,
    }


def save_variant_grid_summary(run_id: str, variant_name: str, grid_summary: Any) -> Path:
    return _write_csv(_run_path(run_id) / "variants" / str(variant_name) / "grid_summary.csv", grid_summary)


def create_pool_snapshot(
    run_id: str,
    variant_name: str,
    tags: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    source_run_path = _run_path(run_id)
    variant_dir = source_run_path / "variants" / str(variant_name)
    pool_item_id = _stamp_id("pool")
    pool_path = POOL_STRATEGIES_ROOT / pool_item_id
    pool_path.mkdir(parents=True, exist_ok=False)

    copied = {
        "manifest_path": _copy_required(source_run_path / "manifest.json", pool_path / "manifest.json", "manifest.json"),
        "input_path": _copy_required(source_run_path / "input.json", pool_path / "input.json", "input.json"),
        "config_path": _copy_required(source_run_path / "config.json", pool_path / "config.json", "config.json"),
        "strategy_path": _copy_required(source_run_path / "strategy.py", pool_path / "strategy.py", "strategy.py"),
        "result_path": _copy_required(variant_dir / "result.json", pool_path / "result.json", f"variant result.json for {variant_name}"),
    }
    daily_results_path = _copy_optional(variant_dir / "daily_results.csv", pool_path / "daily_results.csv")
    trades_path = _copy_optional(variant_dir / "trades.csv", pool_path / "trades.csv")
    if daily_results_path is not None:
        copied["daily_results_path"] = daily_results_path
    if trades_path is not None:
        copied["trades_path"] = trades_path

    tags_path = _write_json(
        pool_path / "tags.json",
        {
            "tags": list(tags or []),
            "source_run_id": run_id,
            "source_variant_name": str(variant_name),
            "created_at": _now(),
        },
    )
    notes_path = pool_path / "notes.md"
    notes_path.write_text(str(note or ""), encoding="utf-8")

    manifest = _read_json(pool_path / "manifest.json")
    manifest.update(
        {
            "pool_item_id": pool_item_id,
            "pool_path": str(pool_path),
            "source_run_id": run_id,
            "source_variant_name": str(variant_name),
            "pool_created_at": _now(),
        }
    )
    _write_json(pool_path / "manifest.json", manifest)

    return {
        "pool_item_id": pool_item_id,
        "pool_path": pool_path,
        "tags_path": tags_path,
        "notes_path": notes_path,
        **copied,
    }
