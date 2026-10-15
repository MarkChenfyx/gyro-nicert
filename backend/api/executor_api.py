from __future__ import annotations

from fastapi import APIRouter

from backend.services import executor_service

router = APIRouter(prefix="/api/executor", tags=["executor"])


@router.get("/runs")
def get_executor_runs() -> dict:
    return executor_service.list_runs()


@router.get("/overview")
def get_executor_overview(run: str) -> dict:
    return executor_service.overview(run)
