from __future__ import annotations

from backend.services import strategy_generation_service


def test_strategy_generation_reports_api_progress(monkeypatch, tmp_path):
    progress_updates: list[tuple[float, str]] = []
    task = {"task_id": "task_generation", "status": "queued", "progress": 0.0}

    monkeypatch.setattr(strategy_generation_service.task_service, "create_task", lambda *args, **kwargs: dict(task))
    monkeypatch.setattr(strategy_generation_service.task_service, "mark_running", lambda *args, **kwargs: dict(task, status="running"))

    def mark_progress(task_id: str, progress: float, message: str | None = None):
        progress_updates.append((progress, message or ""))
        return dict(task, status="running", progress=progress, message=message)

    monkeypatch.setattr(strategy_generation_service.task_service, "mark_progress", mark_progress)
    monkeypatch.setattr(strategy_generation_service.task_service, "mark_completed", lambda *args, **kwargs: dict(task, status="completed", progress=1.0))
    monkeypatch.setattr(
        strategy_generation_service.natural_language_source_service,
        "read_source_file",
        lambda filename: {"name": filename, "text": "生成一个简单趋势策略"},
    )
    monkeypatch.setattr(
        strategy_generation_service,
        "generate_strategy_from_text",
        lambda text, options=None: {
            "success": True,
            "strategy_name": "ProgressStrategy",
            "class_name": "ProgressStrategy",
            "strategy_code": "class ProgressStrategy:\n    pass\n",
            "source_text": text,
        },
    )
    monkeypatch.setattr(
        strategy_generation_service.strategy_service,
        "register_generated_strategy",
        lambda **kwargs: {
            "strategy_id": "strategy_progress",
            "code_path": str(tmp_path / "strategy.py"),
            **kwargs,
        },
    )
    monkeypatch.setattr(
        strategy_generation_service.artifact_repository,
        "create_artifact",
        lambda **kwargs: kwargs,
    )

    payload = strategy_generation_service.generate_and_register_strategy("progress.txt")

    assert payload["strategy"]["strategy_id"] == "strategy_progress"
    assert [progress for progress, _ in progress_updates] == [0.12, 0.25, 0.78, 0.9]
    assert "API" in progress_updates[1][1]
    assert "API" in progress_updates[2][1]
