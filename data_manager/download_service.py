from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from common.time_utils import timestamp_id
from data_manager import coverage_service, market_repository
from data_manager.rqdata_client import get_default_client


class BarClient(Protocol):
    name: str

    def query_bars(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        ...


def _download_task_id() -> str:
    return f"download_{timestamp_id()}_{uuid4().hex[:6]}"


def download_bars(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
    *,
    client: BarClient | None = None,
) -> dict[str, Any]:
    resolved_client = client or get_default_client()
    download_task = market_repository.create_download_task(
        _download_task_id(),
        symbol,
        exchange,
        interval,
        start_date,
        end_date,
        status="running",
    )
    try:
        bars = resolved_client.query_bars(symbol, exchange, interval, start_date, end_date)
        inserted = market_repository.upsert_bars(symbol, exchange, interval, bars, source=resolved_client.name)
        market_repository.update_download_task(str(download_task["download_task_id"]), status="completed")
        return {
            "success": True,
            "download_task": market_repository.get_download_task(str(download_task["download_task_id"])),
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "source": resolved_client.name,
            "bar_count": len(bars),
            "saved_count": inserted,
            "coverage": coverage_service.get_data_coverage(
                symbol,
                exchange,
                interval,
                start_date=start_date,
                end_date=end_date,
                source=resolved_client.name,
            ),
            "error": None,
        }
    except Exception as exc:
        market_repository.update_download_task(str(download_task["download_task_id"]), status="failed", error=str(exc))
        return {
            "success": False,
            "download_task": market_repository.get_download_task(str(download_task["download_task_id"])),
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "source": getattr(resolved_client, "name", "unknown"),
            "bar_count": 0,
            "saved_count": 0,
            "coverage": coverage_service.get_data_coverage(symbol, exchange, interval, source=getattr(resolved_client, "name", "rqdata")),
            "error": str(exc),
        }
