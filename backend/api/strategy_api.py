from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import StrategyGenerateRequest, StrategyInitialReviewRequest, StrategyRepairRequest
from backend.services import strategy_generation_service
from backend.strategy_generation import repair_strategy_code


router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.post("/generate")
def generate_strategy(payload: StrategyGenerateRequest) -> dict:
    return strategy_generation_service.generate_and_register_strategy(
        payload.source_filename,
        options=payload.options,
    )


@router.post("/repair")
def repair_strategy(payload: StrategyRepairRequest) -> dict:
    return repair_strategy_code(
        strategy_name=payload.strategy_name,
        strategy_code=payload.strategy_code,
        vt_symbol=payload.vt_symbol,
        interval=payload.interval,
        options=payload.options,
    )


@router.post("/initial-review")
def initial_review(payload: StrategyInitialReviewRequest) -> dict:
    return strategy_generation_service.create_initial_review(
        payload.run_id,
        force_refresh=payload.force_refresh,
        options=payload.options,
    )
