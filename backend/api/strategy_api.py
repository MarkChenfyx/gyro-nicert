from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import StrategyGenerateRequest, StrategyRepairRequest
from backend.services import strategy_generation_service
from strategy_generation import repair_strategy_code


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
