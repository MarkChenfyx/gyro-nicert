from __future__ import annotations

from datetime import datetime
from typing import Any

from data_manager import market_repository


def _is_date_only(value: str | None) -> bool:
    text = str(value or "").strip()
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text[:10] + "T00:00:00")


def _covers_requested_range(
    local_start: datetime | None,
    local_end: datetime | None,
    requested_start: datetime,
    requested_end: datetime,
    *,
    start_date: str | None,
    end_date: str | None,
) -> bool:
    if not local_start or not local_end:
        return False
    if _is_date_only(start_date) and _is_date_only(end_date):
        return local_start.date() <= requested_start.date() and local_end.date() >= requested_end.date()
    return local_start <= requested_start and local_end >= requested_end


def get_data_coverage(
    symbol: str,
    exchange: str,
    interval: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str = "rqdata",
) -> dict[str, Any]:
    coverage = market_repository.get_coverage(symbol, exchange, interval, source=source)
    requested_start = _parse_dt(start_date)
    requested_end = _parse_dt(end_date)
    local_start = _parse_dt(coverage.get("start_date")) if coverage else None
    local_end = _parse_dt(coverage.get("end_date")) if coverage else None

    if not coverage:
        status = "missing"
    elif requested_start and requested_end:
        status = "covered" if _covers_requested_range(
            local_start,
            local_end,
            requested_start,
            requested_end,
            start_date=start_date,
            end_date=end_date,
        ) else "partial"
    else:
        status = "available"

    missing_ranges: list[dict[str, str]] = []
    if requested_start and requested_end and status != "covered":
        if not local_start or not local_end:
            missing_ranges.append({"start_date": requested_start.isoformat(), "end_date": requested_end.isoformat()})
        else:
            start_missing = local_start.date() > requested_start.date() if _is_date_only(start_date) else local_start > requested_start
            end_missing = local_end.date() < requested_end.date() if _is_date_only(end_date) else local_end < requested_end
            if start_missing:
                missing_ranges.append({"start_date": requested_start.isoformat(), "end_date": local_start.isoformat()})
            if end_missing:
                missing_ranges.append({"start_date": local_end.isoformat(), "end_date": requested_end.isoformat()})

    return {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "source": source,
        "status": status,
        "requested_start": requested_start.isoformat() if requested_start else None,
        "requested_end": requested_end.isoformat() if requested_end else None,
        "local_start": local_start.isoformat() if local_start else None,
        "local_end": local_end.isoformat() if local_end else None,
        "bar_count": int(coverage.get("bar_count") or 0) if coverage else 0,
        "missing_ranges": missing_ranges,
        "coverage": coverage,
    }


def list_symbols(limit: int = 1000) -> dict[str, Any]:
    return {"items": market_repository.list_symbols(limit=limit)}
