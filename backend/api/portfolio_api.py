from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.api.schemas import PortfolioSaveRequest
from backend.services import portfolio_service


router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("")
def list_portfolios(include_archived: bool = False) -> dict:
    return {"items": portfolio_service.list_portfolios(include_archived=include_archived)}


@router.post("")
def create_portfolio(payload: PortfolioSaveRequest) -> dict:
    return portfolio_service.create_portfolio(payload.model_dump())


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: str) -> dict:
    return portfolio_service.get_portfolio_detail(portfolio_id)


@router.put("/{portfolio_id}")
def update_portfolio(portfolio_id: str, payload: PortfolioSaveRequest) -> dict:
    return portfolio_service.update_portfolio(portfolio_id, payload.model_dump())


@router.post("/{portfolio_id}/refresh")
def refresh_portfolio(portfolio_id: str) -> dict:
    return portfolio_service.refresh_portfolio(portfolio_id)


@router.post("/{portfolio_id}/archive")
def archive_portfolio(portfolio_id: str) -> dict:
    return portfolio_service.archive_portfolio(portfolio_id)


@router.get("/{portfolio_id}/export")
def export_portfolio(portfolio_id: str) -> FileResponse:
    path = portfolio_service.portfolio_export_path(portfolio_id)
    return FileResponse(path, media_type="text/csv", filename=f"{portfolio_id}_daily_results.csv")
