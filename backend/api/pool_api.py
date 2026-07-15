from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import PoolAddRequest, PoolCompareRequest, PoolNoteUpdateRequest, PoolRerunRequest
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
        strategy_name=payload.strategy_name,
    )


@router.post("/compare")
def compare_pool_items(payload: PoolCompareRequest) -> dict:
    return pool_service.compare_pool_items(payload.pool_item_ids)


@router.post("/rerun")
def rerun_pool_items(payload: PoolRerunRequest) -> dict:
    return pool_service.rerun_pool_items_to_latest(
        payload.pool_item_ids,
        end_date=payload.end_date,
        start_mode=payload.start_mode,
    )


@router.post("/{pool_item_id}/continue-optimization")
def continue_pool_item_optimization(pool_item_id: str) -> dict:
    return pool_service.continue_optimization_from_pool(pool_item_id)


@router.patch("/{pool_item_id}/notes")
def update_pool_item_notes(pool_item_id: str, payload: PoolNoteUpdateRequest) -> dict:
    try:
        return pool_service.update_pool_item_notes(pool_item_id, payload.note)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.delete("/{pool_item_id}")
def delete_pool_item(pool_item_id: str) -> dict:
    return pool_service.remove_pool_item(pool_item_id)
