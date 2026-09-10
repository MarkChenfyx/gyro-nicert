from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import StrategyResearchHeatmapRequest, StrategyResearchWalkForwardRequest
from backend.services import strategy_research_service, walk_forward_research_service


router = APIRouter(prefix="/api/strategy-research", tags=["strategy-research"])


@router.get("/pool/{pool_item_id}/context")
def get_pool_research_context(pool_item_id: str) -> dict:
    return strategy_research_service.get_pool_research_context(pool_item_id)


@router.post("/pool/{pool_item_id}/ai-overview")
def create_pool_ai_overview(pool_item_id: str, force_refresh: bool = False) -> dict:
    return strategy_research_service.create_pool_ai_overview(
        pool_item_id,
        force_refresh=force_refresh,
    )


@router.post("/pool/{pool_item_id}/heatmap")
def run_pool_parameter_heatmap(pool_item_id: str, payload: StrategyResearchHeatmapRequest) -> dict:
    return strategy_research_service.run_pool_parameter_heatmap(
        pool_item_id,
        x_parameter=payload.x_parameter,
        y_parameter=payload.y_parameter,
        parameter_ranges=payload.parameter_ranges,
        objective=payload.objective,
        max_trials=payload.max_trials,
    )


@router.post("/pool/{pool_item_id}/walk-forward")
def run_pool_walk_forward(pool_item_id: str, payload: StrategyResearchWalkForwardRequest) -> dict:
    return walk_forward_research_service.run_pool_walk_forward(
        pool_item_id,
        training_start_date=payload.training_start_date,
        training_months=payload.training_months,
        test_months=payload.test_months,
        selected_parameters=payload.selected_parameters,
        parameter_ranges=payload.parameter_ranges,
        objective=payload.objective,
        max_trials=payload.max_trials,
    )


@router.post("/pool/{pool_item_id}/walk-forward/{experiment_id}/rank-analysis")
def run_walk_forward_rank_analysis(pool_item_id: str, experiment_id: str) -> dict:
    return walk_forward_research_service.run_walk_forward_rank_analysis(pool_item_id, experiment_id)
