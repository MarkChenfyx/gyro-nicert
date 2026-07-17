from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.schemas import DataDownloadRequest
from backend.data_manager import coverage_service, download_service


router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/coverage")
def get_coverage(
    symbol: str,
    exchange: str,
    interval: str = "1m",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    return coverage_service.get_data_coverage(
        symbol,
        exchange,
        interval,
        start_date=start_date,
        end_date=end_date,
    )


@router.post("/download")
def download_data(payload: DataDownloadRequest) -> dict:
    return download_service.download_bars(
        payload.symbol,
        payload.exchange,
        payload.interval,
        payload.start_date,
        payload.end_date,
    )


@router.get("/symbols")
def list_symbols(limit: int = Query(default=1000, ge=1, le=5000)) -> dict:
    return coverage_service.list_symbols(limit=limit)
