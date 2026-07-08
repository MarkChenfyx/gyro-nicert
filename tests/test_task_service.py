from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from backend.domain.enums import TaskStatus, TaskType
from backend.services import task_service


def setup_module() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "init_db.py")], cwd=root, check=True)


def test_task_service_lifecycle() -> None:
    created = task_service.create_task(TaskType.STRATEGY_GENERATION.value, message="queued")
    task_id = created["task_id"]
    assert created["status"] == TaskStatus.QUEUED.value
    assert created["message"] == "queued"

    running = task_service.mark_running(task_id, message="running")
    assert running["status"] == TaskStatus.RUNNING.value
    assert running["message"] == "running"

    completed = task_service.mark_completed(task_id, message="done")
    assert completed["status"] == TaskStatus.COMPLETED.value
    assert completed["progress"] == 1.0

    failed_task = task_service.create_task(TaskType.BACKTEST.value)
    failed = task_service.mark_failed(failed_task["task_id"], error="boom", message="failed")
    assert failed["status"] == TaskStatus.FAILED.value
    assert failed["error"] == "boom"

    tasks = task_service.list_tasks(limit=10)
    ids = {task["task_id"] for task in tasks}
    assert task_id in ids
    assert failed_task["task_id"] in ids

