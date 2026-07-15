from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services import optimization_service
from backend.services import query_service


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(limit: int = Query(default=50, ge=1, le=1000)) -> dict:
    return optimization_service.list_optimizable_runs(limit=limit)


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    return query_service.get_run_detail(run_id)


@router.get("/{run_id}/variants/{variant_name}/curve")
def get_variant_curve(run_id: str, variant_name: str) -> dict:
    return query_service.get_variant_curve(run_id, variant_name)


@router.get("/{run_id}/variants/{variant_name}/candidates/{candidate_label}/curve")
def get_grid_candidate_curve(run_id: str, variant_name: str, candidate_label: str) -> dict:
    try:
        return query_service.get_grid_candidate_curve(run_id, variant_name, candidate_label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{run_id}/variants/{variant_name}/trades")
def get_variant_trades(run_id: str, variant_name: str) -> dict:
    return query_service.get_variant_trades(run_id, variant_name)
