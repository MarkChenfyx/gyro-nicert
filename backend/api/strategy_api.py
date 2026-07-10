from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import StrategyGenerateRequest
from backend.services import strategy_generation_service


router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.post("/generate")
def generate_strategy(payload: StrategyGenerateRequest) -> dict:
    return strategy_generation_service.generate_and_register_strategy(
        payload.source_filename,
        options=payload.options,
    )
