from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.schemas import LiveSnapshotRequest, LiveSourceImportRequest, LiveTrackRequest
from backend.services import live_scheduler, live_service


router = APIRouter(prefix="/api/live", tags=["live"])


@router.get("/local-status")
def get_local_source_status() -> dict:
    return live_service.local_source_status()


@router.get("/automation-status")
def get_live_automation_status() -> dict:
    return live_scheduler.status()


@router.get("/sources")
def list_live_sources() -> dict:
    return {"items": live_service.list_sources()}


@router.post("/sources")
def import_live_source(payload: LiveSourceImportRequest) -> dict:
    return live_service.import_source(payload.model_dump())


@router.get("/sources/{source_id}")
def get_live_source(source_id: str) -> dict:
    return live_service.get_source_detail(source_id)


@router.delete("/sources/{source_id}")
def delete_live_source(source_id: str) -> dict:
    return live_service.delete_source(source_id)


@router.post("/sources/{source_id}/snapshots")
def import_live_snapshot(source_id: str, payload: LiveSnapshotRequest) -> dict:
    return {"snapshot": live_service.import_snapshot(source_id, payload.model_dump())}


@router.post("/sources/{source_id}/track")
def track_live_day(source_id: str, payload: LiveTrackRequest) -> dict:
    return live_service.track_day(
        source_id, payload.trade_date, update_data=payload.update_data
    )


@router.get("/sources/{source_id}/records")
def list_live_records(source_id: str, limit: int = Query(default=60, ge=1, le=365)) -> dict:
    return {"items": live_service.list_daily_records(source_id, limit=limit)}


@router.get("/sources/{source_id}/records/{trade_date}")
def get_live_record(source_id: str, trade_date: str) -> dict:
    return live_service.get_daily_record(source_id, trade_date)
