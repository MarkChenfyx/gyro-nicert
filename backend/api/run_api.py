from __future__ import annotations

from fastapi import APIRouter

from backend.services import query_service


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    return query_service.get_run_detail(run_id)


@router.get("/{run_id}/variants/{variant_name}/curve")
def get_variant_curve(run_id: str, variant_name: str) -> dict:
    return query_service.get_variant_curve(run_id, variant_name)


@router.get("/{run_id}/variants/{variant_name}/trades")
def get_variant_trades(run_id: str, variant_name: str) -> dict:
    return query_service.get_variant_trades(run_id, variant_name)

