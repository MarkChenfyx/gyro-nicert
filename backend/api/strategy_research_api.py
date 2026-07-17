from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import StrategyResearchHeatmapRequest
from backend.services import strategy_research_service


router = APIRouter(prefix="/api/strategy-research", tags=["strategy-research"])


@router.get("/pool/{pool_item_id}/context")
def get_pool_research_context(pool_item_id: str) -> dict:
    return strategy_research_service.get_pool_research_context(pool_item_id)


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
