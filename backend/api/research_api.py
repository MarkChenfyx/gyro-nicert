from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import ResearchBaselineCreateRequest, ResearchCodeBaselineCreateRequest, ResearchCreateRequest
from backend.services import research_workflow_service


router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/symbols")
def research_symbols() -> dict:
    import json
    from pathlib import Path
    from backend.repositories import run_repository
    symbols = []
    for run in run_repository.list_runs(limit=1000):
        try:
            config = json.loads((Path(run["runtime_path"]) / "config.json").read_text(encoding="utf-8"))
            symbol = str(config.get("vt_symbol") or "").strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        except (OSError, ValueError):
            continue
    return {"symbols": symbols}


@router.post("/create")
def create_research(payload: ResearchCreateRequest) -> dict:
    vt_symbol = f"{payload.symbol}.{payload.exchange}"
    return research_workflow_service.create_strategy_research_run(
        payload.source_filename,
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


@router.post("/baseline")
def create_research_baseline(payload: ResearchBaselineCreateRequest) -> dict:
    vt_symbol = f"{payload.symbol}.{payload.exchange}"
    return research_workflow_service.create_baseline_run_for_strategy(
        payload.strategy_id,
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


@router.post("/baseline-from-code")
def create_research_baseline_from_code(payload: ResearchCodeBaselineCreateRequest) -> dict:
    vt_symbol = f"{payload.symbol}.{payload.exchange}"
    return research_workflow_service.create_baseline_run_from_manual_code(
        strategy_name=payload.strategy_name,
        strategy_code=payload.strategy_code,
        model_files=payload.model_files,
        strategy_parameters=payload.parameters,
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
