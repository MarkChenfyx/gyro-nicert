from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.schemas import TaskArchiveRequest
from backend.services import task_service


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    limit: int = Query(default=100, ge=1, le=1000),
    view: str = Query(default="recent", pattern="^(active|recent|archived|all)$"),
    status: str | None = None,
) -> dict:
    return {"tasks": task_service.list_tasks(limit=limit, view=view, status=status)}


@router.post("/archive")
def archive_tasks(payload: TaskArchiveRequest) -> dict:
    if payload.scope != "terminal":
        raise ValueError("Only terminal tasks can be archived")
    return {"archived_count": task_service.archive_terminal_tasks()}


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    task = task_service.get_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task not found: {task_id}")
    return task
