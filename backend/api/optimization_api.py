from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import (
    OptimizationCurveSnapshotCreateRequest,
    OptimizationCurveSnapshotUpdateRequest,
    OptimizationRunRequest,
    OptimizationSearchSpaceRequest,
    OptimizationSuggestSpaceRequest,
)
from backend.services import optimization_curve_snapshot_service, optimization_service


router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.get("/methods")
def get_methods() -> dict:
    return optimization_service.list_optimization_methods()


@router.get("/curve-snapshots")
def list_curve_snapshots() -> dict:
    return {"items": optimization_curve_snapshot_service.list_curve_snapshots()}


@router.post("/curve-snapshots")
def create_curve_snapshot(payload: OptimizationCurveSnapshotCreateRequest) -> dict:
    return {
        "item": optimization_curve_snapshot_service.create_curve_snapshot(
            run_id=payload.run_id,
            variant_name=payload.variant_name,
            name=payload.name,
        )
    }


@router.patch("/curve-snapshots/{snapshot_id}")
def update_curve_snapshot(snapshot_id: str, payload: OptimizationCurveSnapshotUpdateRequest) -> dict:
    return {"item": optimization_curve_snapshot_service.rename_curve_snapshot(snapshot_id, payload.name)}


@router.delete("/curve-snapshots/{snapshot_id}")
def delete_curve_snapshot(snapshot_id: str) -> dict:
    optimization_curve_snapshot_service.delete_curve_snapshot(snapshot_id)
    return {"deleted": True, "snapshot_id": snapshot_id}


@router.post("/search-space")
def get_search_space(payload: OptimizationSearchSpaceRequest) -> dict:
    return optimization_service.get_search_space(payload.run_id, payload.variant_name)


@router.post("/suggest-space")
def suggest_search_space(payload: OptimizationSuggestSpaceRequest) -> dict:
    return optimization_service.suggest_optimization_space(
        payload.run_id,
        payload.variant_name,
        options=payload.options,
    )


@router.post("/run")
def run_optimization(payload: OptimizationRunRequest) -> dict:
    return optimization_service.run_optimization(
        run_id=payload.run_id,
        variant_name=payload.variant_name,
        method=payload.method,
        base_parameters=payload.base_parameters,
        selected_parameters=payload.selected_parameters,
        parameter_ranges=payload.parameter_ranges,
        constraints=payload.constraints,
        virtual_parameters=payload.virtual_parameters,
        objective=payload.objective,
        max_trials=payload.max_trials,
        max_workers=payload.max_workers,
    )
