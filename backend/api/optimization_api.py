from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import OptimizationRunRequest, OptimizationSearchSpaceRequest, OptimizationSuggestSpaceRequest
from backend.services import optimization_service


router = APIRouter(prefix="/api/optimization", tags=["optimization"])


@router.get("/methods")
def get_methods() -> dict:
    return optimization_service.list_optimization_methods()


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
        selected_parameters=payload.selected_parameters,
        parameter_ranges=payload.parameter_ranges,
        constraints=payload.constraints,
        virtual_parameters=payload.virtual_parameters,
        objective=payload.objective,
        max_trials=payload.max_trials,
    )
