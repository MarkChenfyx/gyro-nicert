from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import json

from backend.repositories import artifact_repository, run_repository, variant_repository
from backend.services import pool_service


def _read_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    return json.loads(candidate.read_text(encoding="utf-8"))


def _read_csv(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"columns": [], "data": []}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {"columns": [], "data": []}
    with candidate.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        columns = list(reader.fieldnames or [])
    return {"columns": columns, "data": rows}


def get_run_detail(run_id: str) -> dict[str, Any]:
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    run_path = Path(str(run["runtime_path"]))
    variants = variant_repository.list_variants(run_id)
    return {
        "run": run,
        "variants": variants,
        "artifacts": artifact_repository.list_artifacts("run", run_id),
        "variant_artifacts": {
            str(variant["variant_id"]): artifact_repository.list_artifacts("variant", str(variant["variant_id"]))
            for variant in variants
        },
        "manifest": _read_json(run_path / "manifest.json"),
        "input": _read_json(run_path / "input.json"),
        "config": _read_json(run_path / "config.json"),
    }


def get_variant_curve(run_id: str, variant_name: str) -> dict[str, Any]:
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")
    return _read_csv(variant.get("daily_results_path"))


def get_variant_trades(run_id: str, variant_name: str) -> dict[str, Any]:
    variant = variant_repository.get_variant_by_run_and_name(run_id, variant_name)
    if variant is None:
        raise FileNotFoundError(f"Variant not found: {run_id} / {variant_name}")
    return _read_csv(variant.get("trades_path"))


def get_pool_curve(pool_item_id: str) -> dict[str, Any]:
    detail = pool_service.get_pool_item_detail(pool_item_id)
    return _read_csv(detail.get("daily_results_path"))

