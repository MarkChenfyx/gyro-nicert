from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.hashing import compute_sha256
from backend.domain.enums import ArtifactType, RunType, TaskStatus, TaskType, VariantType
from backend.repositories import artifact_repository, run_repository, variant_repository
from backend.services import artifact_service, task_service


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


def create_baseline_run(
    strategy: dict[str, Any],
    source_text: str,
    config_payload: dict[str, Any],
    strategy_code: str,
    result_payload: dict[str, Any],
    daily_results: Any = None,
    trades: Any = None,
) -> dict[str, Any]:
    strategy_id = str(strategy["strategy_id"])
    task = task_service.create_task(TaskType.BACKTEST.value, message="Baseline run queued", related_strategy_id=strategy_id)
    try:
        task = task_service.mark_running(task["task_id"], message="Creating baseline run artifacts")
        run_artifact = artifact_service.create_run_artifact(
            run_type=RunType.BASELINE.value,
            strategy=strategy,
            source="service_test",
        )
        run_id = str(run_artifact["run_id"])
        run_path = Path(run_artifact["run_path"])
        manifest_path = Path(run_artifact["manifest_path"])
        input_path = artifact_service.save_run_input(run_id, {"source_text": source_text})
        config_path = artifact_service.save_run_config(run_id, config_payload)
        strategy_path = artifact_service.save_strategy_code_to_run(run_id, strategy_code)
        variant_artifacts = artifact_service.save_variant_result(
            run_id,
            VariantType.BASELINE.value,
            result_payload,
            daily_results=daily_results,
            trades=trades,
        )

        run = run_repository.create_run(
            run_id=run_id,
            strategy_id=strategy_id,
            task_id=task["task_id"],
            run_type=RunType.BASELINE.value,
            status=TaskStatus.COMPLETED.value,
            runtime_path=str(run_path),
        )
        variant = variant_repository.create_variant(
            None,
            run_id=run_id,
            variant_name=VariantType.BASELINE.value,
            params_hash=None,
            config_path=str(config_path),
            result_path=str(variant_artifacts["result_path"]),
            daily_results_path=str(variant_artifacts["daily_results_path"]) if variant_artifacts["daily_results_path"] else None,
            trades_path=str(variant_artifacts["trades_path"]) if variant_artifacts["trades_path"] else None,
        )

        _register_artifact("run", run_id, ArtifactType.MANIFEST.value, manifest_path)
        _register_artifact("run", run_id, ArtifactType.INPUT.value, input_path)
        _register_artifact("run", run_id, ArtifactType.CONFIG.value, config_path)
        _register_artifact("run", run_id, ArtifactType.STRATEGY_CODE.value, strategy_path)
        _register_artifact("variant", variant["variant_id"], ArtifactType.RESULT.value, variant_artifacts["result_path"])
        _register_artifact("variant", variant["variant_id"], ArtifactType.DAILY_RESULTS.value, variant_artifacts["daily_results_path"])
        _register_artifact("variant", variant["variant_id"], ArtifactType.TRADES.value, variant_artifacts["trades_path"])

        task = task_service.mark_completed(task["task_id"], message="Baseline run completed")
        return {
            "task": task,
            "run": run,
            "variant": variant,
            "artifact_paths": {
                "manifest_path": str(manifest_path),
                "input_path": str(input_path),
                "config_path": str(config_path),
                "strategy_path": str(strategy_path),
                "result_path": str(variant_artifacts["result_path"]),
                "daily_results_path": str(variant_artifacts["daily_results_path"] or ""),
                "trades_path": str(variant_artifacts["trades_path"] or ""),
            },
        }
    except Exception as exc:
        task_service.mark_failed(task["task_id"], error=str(exc), message="Baseline run failed")
        raise
