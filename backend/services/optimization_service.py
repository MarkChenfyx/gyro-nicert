from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from backend.core.hashing import compute_sha256
from backend.domain.enums import ArtifactType, TaskStatus, TaskType
from backend.repositories import artifact_repository, run_repository, strategy_repository, variant_repository
from backend.services import artifact_service, task_service
from strategy_optimization import optimize_parameters
from strategy_optimization.optimizers.registry import list_methods, resolve_method, variant_for_method
from strategy_optimization.search_space import build_parameter_inventory, read_json_file


def _register_artifact(owner_type: str, owner_id: str, artifact_type: str, path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    return artifact_repository.create_artifact(
        owner_type=owner_type,
        owner_id=owner_id,
        artifact_type=artifact_type,
        path=str(candidate),
        sha256=compute_sha256(candidate),
    )


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return {}
    return json.loads(candidate.read_text(encoding="utf-8"))


def _run_context(run_id: str) -> dict[str, Any]:
    run = run_repository.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")
    run_path = Path(str(run["runtime_path"]))
    strategy_path = run_path / "strategy.py"
    if not strategy_path.exists():
        raise FileNotFoundError(f"Strategy code not found for run: {run_id}")
    strategy = strategy_repository.get_strategy(str(run["strategy_id"])) or {}
    report_path = Path(str(strategy.get("code_path") or "")).parent / "generation_report.json" if strategy.get("code_path") else None
    config = _read_json(run_path / "config.json")
    report = read_json_file(report_path)
    strategy_code = strategy_path.read_text(encoding="utf-8")
    inventory = build_parameter_inventory(strategy_code=strategy_code, generation_report=report)
    vt_symbol = str(config.get("vt_symbol") or f"{config.get('symbol', '')}.{config.get('exchange', '')}").strip(".")
    return {
        "run": run,
        "run_path": run_path,
        "strategy": strategy,
        "strategy_code": strategy_code,
        "generation_report": report,
        "config": config,
        "inventory": inventory,
        "vt_symbol": vt_symbol,
    }


def list_optimization_methods() -> dict[str, Any]:
    return {"methods": list_methods(include_mock=False)}


def list_optimizable_runs(limit: int = 100) -> dict[str, Any]:
    rows = []
    for run in run_repository.list_runs(limit=limit):
        config = _read_json(Path(str(run["runtime_path"])) / "config.json")
        strategy = strategy_repository.get_strategy(str(run["strategy_id"])) or {}
        rows.append(
            {
                **run,
                "strategy_name": strategy.get("strategy_name") or run.get("strategy_id"),
                "vt_symbol": config.get("vt_symbol") or f"{config.get('symbol', '')}.{config.get('exchange', '')}".strip("."),
                "interval": config.get("interval") or "",
                "mode": config.get("mode") or "",
            }
        )
    return {"runs": rows}


def get_search_space(run_id: str, variant_name: str = "baseline") -> dict[str, Any]:
    context = _run_context(run_id)
    inventory = dict(context["inventory"])
    return {
        "run_id": run_id,
        "variant_name": variant_name,
        "vt_symbol": context["vt_symbol"],
        "base_parameters": inventory.get("base_parameters") or {},
        "parameters": inventory.get("parameters") or [],
        "hidden_parameters": inventory.get("hidden_parameters") or [],
        "diagnostics": inventory.get("diagnostics") or [],
    }


def _validate_selected_parameters(search_space: dict[str, Any], selected: list[str], parameter_ranges: dict[str, Any]) -> None:
    visible = {str(item["name"]): item for item in search_space.get("parameters") or []}
    hidden = {str(item["name"]): item for item in search_space.get("hidden_parameters") or []}
    if not selected:
        raise ValueError("Please select at least one parameter to optimize.")
    blocked = [name for name in selected if name in hidden or name not in visible]
    if blocked:
        raise ValueError(f"Selected parameters are not tunable or hidden: {', '.join(blocked)}")
    missing = [name for name in selected if name not in parameter_ranges]
    if missing:
        raise ValueError(f"Missing parameter ranges: {', '.join(missing)}")


def _result_payload(optimization: dict[str, Any], selected_variant: str, artifact_paths: dict[str, str]) -> dict[str, Any]:
    recommended = dict(optimization.get("recommended") or {})
    metrics = dict(recommended.get("metrics") or {})
    return {
        "metrics": metrics,
        "recommended": {
            "label": recommended.get("label"),
            "parameters": recommended.get("parameters") or {},
            "overrides": recommended.get("overrides") or {},
            "score": recommended.get("score"),
            "metrics": metrics,
        },
        "selected_variant": selected_variant,
        "optimizer_name": optimization.get("optimizer_name"),
        "optimizer_version": optimization.get("optimizer_version"),
        "diagnostics": optimization.get("diagnostics") or [],
        "artifact_paths": artifact_paths,
        "success": bool(optimization.get("success")),
        "error": optimization.get("error"),
    }


def run_optimization(
    *,
    run_id: str,
    variant_name: str = "baseline",
    method: str = "manual_grid",
    selected_parameters: list[str] | None = None,
    parameter_ranges: dict[str, Any] | None = None,
    objective: str = "sharpe",
    max_trials: int = 200,
) -> dict[str, Any]:
    selected = [str(item) for item in list(selected_parameters or []) if str(item).strip()]
    ranges = dict(parameter_ranges or {})
    search_space = get_search_space(run_id, variant_name)
    resolved_method = resolve_method({"method": method}, {})
    if resolved_method == "auto" and not selected:
        selected = [str(item["name"]) for item in search_space.get("parameters") or [] if item.get("tunable")]
        ranges = {
            name: next(item for item in search_space.get("parameters") or [] if str(item["name"]) == name)
            for name in selected
        }
    _validate_selected_parameters(search_space, selected, ranges)

    context = _run_context(run_id)
    config = {**dict(context["config"]), "mode": dict(context["config"]).get("mode") or "real", "max_trials": max_trials}
    resolved_method = resolve_method({"method": resolved_method}, config)
    selected_variant = variant_for_method(resolved_method)
    task = task_service.create_task(TaskType.OPTIMIZATION.value, message="Optimization queued", related_run_id=run_id, related_strategy_id=str(context["run"]["strategy_id"]))
    try:
        task = task_service.mark_running(task["task_id"], message=f"Running {resolved_method} optimization")
        optimization = optimize_parameters(
            strategy_code=str(context["strategy_code"]),
            class_name=str(context["inventory"].get("class_name") or ""),
            vt_symbol=str(context["vt_symbol"]),
            base_parameters=dict(search_space.get("base_parameters") or {}),
            parameter_space=ranges,
            backtest_config=config,
            objective=objective,
            options={
                "method": resolved_method,
                "selected_parameters": selected,
                "max_trials": max_trials,
            },
        )
        if not optimization.get("success"):
            raise RuntimeError(str(optimization.get("error") or "optimization failed"))
        best_result = dict(optimization.get("best_result") or {})
        result_without_rows = dict(best_result)
        result_without_rows.pop("daily_results", None)
        result_without_rows.pop("trades", None)
        result_without_rows["metrics"] = dict(best_result.get("metrics") or dict(optimization.get("recommended") or {}).get("metrics") or {})

        variant_artifacts = artifact_service.save_variant_result(
            run_id,
            selected_variant,
            {},
            daily_results=best_result.get("daily_results"),
            trades=best_result.get("trades"),
        )
        grid_summary_path = artifact_service.save_variant_grid_summary(run_id, selected_variant, optimization.get("grid_summary") or [])
        artifact_paths = {
            "result_path": str(variant_artifacts["result_path"]),
            "daily_results_path": str(variant_artifacts["daily_results_path"] or ""),
            "trades_path": str(variant_artifacts["trades_path"] or ""),
            "grid_summary_path": str(grid_summary_path),
        }
        payload = _result_payload({**optimization, "recommended": optimization.get("recommended") or {}}, selected_variant, artifact_paths)
        payload["metrics"] = result_without_rows["metrics"]
        variant_artifacts["result_path"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        variant = variant_repository.create_variant(
            None,
            run_id=run_id,
            variant_name=selected_variant,
            params_hash=None,
            config_path=str(Path(str(context["run_path"])) / "config.json"),
            result_path=str(variant_artifacts["result_path"]),
            daily_results_path=str(variant_artifacts["daily_results_path"]) if variant_artifacts["daily_results_path"] else None,
            trades_path=str(variant_artifacts["trades_path"]) if variant_artifacts["trades_path"] else None,
        )
        _register_artifact("variant", variant["variant_id"], ArtifactType.RESULT.value, variant_artifacts["result_path"])
        _register_artifact("variant", variant["variant_id"], ArtifactType.DAILY_RESULTS.value, variant_artifacts["daily_results_path"])
        _register_artifact("variant", variant["variant_id"], ArtifactType.TRADES.value, variant_artifacts["trades_path"])
        _register_artifact("variant", variant["variant_id"], ArtifactType.GRID_SUMMARY.value, grid_summary_path)
        task = task_service.mark_completed(task["task_id"], message="Optimization completed")
        return {
            "task": task,
            "run": context["run"],
            "variant": variant,
            "selected_variant": selected_variant,
            "optimization": payload,
            "grid_summary": optimization.get("grid_summary") or [],
            "artifact_paths": artifact_paths,
            "error": None,
        }
    except Exception as exc:
        failed = task_service.mark_failed(task["task_id"], error=str(exc), message="Optimization failed")
        return {
            "task": failed,
            "run": context["run"],
            "variant": None,
            "selected_variant": selected_variant,
            "optimization": {},
            "grid_summary": [],
            "artifact_paths": {},
            "error": str(exc),
        }
