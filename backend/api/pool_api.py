from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.schemas import PoolAddRequest
from backend.services import pool_service, query_service


router = APIRouter(prefix="/api/pool", tags=["pool"])


@router.post("/add")
def add_to_pool(payload: PoolAddRequest) -> dict:
    return pool_service.add_variant_to_pool(
        payload.run_id,
        payload.variant_name,
        tags=payload.tags,
        note=payload.note,
        vt_symbol=payload.vt_symbol,
    )


@router.get("")
def list_pool_items(
    keyword: str | None = None,
    vt_symbol: str | None = None,
    min_sharpe: float | None = None,
    tag: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    return {
        "items": pool_service.list_pool_items(
            keyword=keyword,
            vt_symbol=vt_symbol,
            min_sharpe=min_sharpe,
            tag=tag,
            sort_by=sort_by,
            order=order,
            limit=limit,
        )
    }


@router.get("/{pool_item_id}")
def get_pool_item(pool_item_id: str) -> dict:
    return pool_service.get_pool_item_detail(pool_item_id)


@router.get("/{pool_item_id}/curve")
def get_pool_curve(pool_item_id: str) -> dict:
    return query_service.get_pool_curve(pool_item_id)

