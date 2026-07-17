from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4
import csv
import json
import re
import shutil

from backend.common.time_utils import now_beijing, now_iso, timestamp_id
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


def _pool_snapshot_parameters(config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Resolve the selected variant's parameters for its independent pool snapshot."""
    recommended = result.get("recommended")
    for candidate in (
        recommended.get("parameters") if isinstance(recommended, dict) else None,
        result.get("params"),
        result.get("parameters"),
        config.get("parameters"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def create_run_artifact(
    run_type: str,
    strategy: dict[str, Any],
    source: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    if lineage:
        manifest["lineage"] = dict(lineage)
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


def _safe_storage_component(value: str, label: str) -> str:
    component = str(value or "").strip()
    if not component or component in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", component):
        raise ValueError(f"Invalid {label}: {value}")
    return component


def _candidate_curves_dir(run_id: str, variant_name: str) -> Path:
    safe_run_id = _safe_storage_component(run_id, "run_id")
    safe_variant_name = _safe_storage_component(variant_name, "variant_name")
    runs_root = RUNS_ROOT.resolve()
    candidate_dir = (runs_root / safe_run_id / "variants" / safe_variant_name / "candidates").resolve()
    if runs_root not in candidate_dir.parents:
        raise ValueError("Candidate curve directory is outside runtime runs storage")
    return candidate_dir


def candidate_curve_path(run_id: str, variant_name: str, candidate_label: str) -> Path:
    safe_label = _safe_storage_component(candidate_label, "candidate_label")
    candidate_dir = _candidate_curves_dir(run_id, variant_name)
    path = (candidate_dir / safe_label / "daily_results.csv").resolve()
    if candidate_dir not in path.parents:
        raise ValueError("Candidate curve path is outside its variant directory")
    return path


def save_variant_candidate_curves(run_id: str, variant_name: str, candidates: Any) -> Path:
    candidate_dir = _candidate_curves_dir(run_id, variant_name)
    staging_dir = candidate_dir.with_name(f"{candidate_dir.name}.tmp_{uuid4().hex[:8]}")
    staging_dir.mkdir(parents=True, exist_ok=False)
    try:
        for candidate in list(candidates or [])[:10]:
            label = _safe_storage_component(str(candidate.get("label") or ""), "candidate_label")
            _write_csv(staging_dir / label / "daily_results.csv", candidate.get("daily_results") or [])
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        staging_dir.replace(candidate_dir)
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return candidate_dir


def create_pool_snapshot(
    run_id: str,
    variant_name: str,
    tags: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    source_run_path = _run_path(run_id)
    variant_dir = source_run_path / "variants" / str(variant_name)
    pooled_at = now_beijing()
    base_pool_version = pooled_at.strftime("%Y%m%d_%H%M%S")
    suffix = 1
    while True:
        pool_version = base_pool_version if suffix == 1 else f"{base_pool_version}_{suffix:02d}"
        pool_item_id = f"pool_{pool_version}"
        pool_path = POOL_STRATEGIES_ROOT / pool_item_id
        try:
            pool_path.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            suffix += 1
    created_at = pooled_at.isoformat()

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

    # A run config contains the baseline parameters.  A manual-grid snapshot must
    # instead make the selected variant's final parameters its canonical config;
    # all later pool reruns and continued optimization read from this snapshot.
    pool_config = _read_json(pool_path / "config.json")
    variant_result = _read_json(pool_path / "result.json")
    snapshot_parameters = _pool_snapshot_parameters(pool_config, variant_result)
    if snapshot_parameters:
        pool_config["parameters"] = snapshot_parameters
        _write_json(pool_path / "config.json", pool_config)

    tags_path = _write_json(
        pool_path / "tags.json",
        {
            "tags": list(tags or []),
            "source_run_id": run_id,
            "source_variant_name": str(variant_name),
            "created_at": created_at,
        },
    )
    notes_path = pool_path / "notes.md"
    notes_path.write_text(str(note or ""), encoding="utf-8")

    manifest = _read_json(pool_path / "manifest.json")
    run_lineage = dict(manifest.get("lineage") or {})
    source_strategy_version = str(
        run_lineage.get("source_strategy_version")
        or manifest.get("source_strategy_version")
        or manifest.get("strategy_version")
        or ""
    )
    if run_lineage.get("source_type") == "pool_item":
        parent_pool_item_id = str(run_lineage.get("source_pool_item_id") or run_lineage.get("pool_item_id") or "")
        parent_pool_version = str(
            run_lineage.get("source_pool_version")
            or (parent_pool_item_id[5:] if parent_pool_item_id.startswith("pool_") else "")
        )
        manifest["lineage"] = {
            "parent_pool_item_id": parent_pool_item_id,
            "parent_pool_version": parent_pool_version,
            "source_strategy_version": source_strategy_version,
            "source_variant": str(variant_name),
            "operation": "optimized_and_repooled",
        }
    manifest.update(
        {
            "pool_item_id": pool_item_id,
            "pool_version": pool_version,
            "pool_path": str(pool_path),
            "source_run_id": run_id,
            "source_variant_name": str(variant_name),
            "source_strategy_version": source_strategy_version,
            "strategy_version": pool_version,
            "pool_created_at": created_at,
        }
    )
    _write_json(pool_path / "manifest.json", manifest)

    return {
        "pool_item_id": pool_item_id,
        "pool_version": pool_version,
        "created_at": created_at,
        "source_strategy_version": source_strategy_version,
        "pool_path": pool_path,
        "tags_path": tags_path,
        "notes_path": notes_path,
        **copied,
    }
