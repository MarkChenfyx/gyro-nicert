from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import ResearchCreateRequest
from backend.services import research_workflow_service


router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("/create")
def create_research(payload: ResearchCreateRequest) -> dict:
    vt_symbol = f"{payload.symbol}.{payload.exchange}"
    return research_workflow_service.create_strategy_research_run(
        payload.source_text,
        options=payload.options,
        config_payload={
            "vt_symbol": vt_symbol,
            "symbol": payload.symbol,
            "exchange": payload.exchange,
            "interval": payload.interval,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "capital": payload.capital,
            "rate": payload.rate,
            "slippage": payload.slippage,
            "size": payload.size,
            "pricetick": payload.pricetick,
            "mode": payload.mode,
        },
    )
