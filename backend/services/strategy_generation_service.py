from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from backend.core.hashing import compute_sha256
from backend.domain.enums import ArtifactType, TaskType
from backend.repositories import artifact_repository
from backend.services import natural_language_source_service, strategy_service, task_service
from backend.strategy_generation import generate_strategy_from_text


def _write_generation_report(strategy_code_path: str, report: dict[str, Any]) -> Path:
    report_path = Path(strategy_code_path).parent / "generation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _validate_generation_result(result: dict[str, Any]) -> None:
    if not bool(result.get("success")):
        raise ValueError(str(result.get("error") or "strategy generation failed"))
    if not str(result.get("strategy_code") or "").strip():
        raise ValueError("strategy generation returned empty strategy_code")
    if not str(result.get("strategy_name") or "").strip() and not str(result.get("class_name") or "").strip():
        raise ValueError("strategy generation returned neither strategy_name nor class_name")


def generate_and_register_strategy(source_filename: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    task_label = f"{source_filename} · 策略生成"
    task = task_service.create_task(TaskType.STRATEGY_GENERATION.value, message=task_label)
    generation_result: dict[str, Any] = {}
    try:
        task = task_service.mark_running(task["task_id"], message=f"{source_filename} · 正在生成策略代码")
        task = task_service.mark_progress(task["task_id"], 0.12, message=f"{source_filename} · 正在读取自然语言文档")
        source_payload = natural_language_source_service.read_source_file(source_filename)
        source_text = str(source_payload.get("text") or "")
        task = task_service.mark_progress(task["task_id"], 0.25, message=f"{source_filename} · 已调用生成 API，正在等待返回")
        generation_result = generate_strategy_from_text(source_text, options=options)
        task = task_service.mark_progress(task["task_id"], 0.78, message=f"{source_filename} · 生成 API 已返回，正在校验代码")
        _validate_generation_result(generation_result)

        task = task_service.mark_progress(task["task_id"], 0.9, message=f"{source_filename} · 代码校验通过，正在保存 strategy.py")
        strategy_name = str(generation_result.get("strategy_name") or generation_result.get("class_name") or source_payload.get("name") or "Generated Strategy")
        strategy = strategy_service.register_generated_strategy(
            strategy_name=strategy_name,
            source_text=str(generation_result.get("source_text") or source_text),
            code=str(generation_result["strategy_code"]),
            source_filename=str(source_payload.get("name") or source_filename),
            class_name=str(generation_result.get("class_name") or "").strip() or None,
        )
        report_path = _write_generation_report(strategy["code_path"], generation_result)
        report_artifact = artifact_repository.create_artifact(
            owner_type="strategy",
            owner_id=strategy["strategy_id"],
            artifact_type=ArtifactType.GENERATION_REPORT.value,
            path=str(report_path),
            sha256=compute_sha256(report_path),
        )
        task = task_service.mark_completed(task["task_id"], message=f"{source_filename} · 策略生成完成")
        return {
            "task": task,
            "strategy": strategy,
            "generation": generation_result,
            "generation_report_path": str(report_path),
            "generation_report_artifact": report_artifact,
        }
    except Exception as exc:
        failed_task = task_service.mark_failed(task["task_id"], error=str(exc), message=f"{source_filename} · 策略生成失败")
        return {
            "task": failed_task,
            "strategy": None,
            "generation": generation_result,
            "generation_report_path": "",
            "generation_report_artifact": None,
            "error": str(exc),
        }
