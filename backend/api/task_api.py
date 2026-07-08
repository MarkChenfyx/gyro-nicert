from __future__ import annotations

from fastapi import APIRouter, Query

from backend.services import task_service


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    return {"tasks": task_service.list_tasks(limit=limit)}


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    task = task_service.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task not found: {task_id}")
    return task

