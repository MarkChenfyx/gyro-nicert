from __future__ import annotations

from uuid import uuid4

from data_manager import coverage_service, download_service


class FakeBarClient:
    name = "rqdata"

    def query_bars(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> list[dict]:
        return [
            {
                "datetime": "2024-01-02T09:31:00",
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "volume": 1000,
                "turnover": 1100,
                "open_interest": None,
            },
            {
                "datetime": "2024-01-02T09:32:00",
                "open": 1.1,
                "high": 1.3,
                "low": 1.0,
                "close": 1.2,
                "volume": 1200,
                "turnover": 1400,
                "open_interest": None,
            },
        ]


def test_download_bars_with_fake_client_updates_coverage() -> None:
    symbol = f"T{uuid4().hex[:8]}"
    payload = download_service.download_bars(
        symbol,
        "SSE",
        "1m",
        "2024-01-02",
        "2024-01-02",
        client=FakeBarClient(),
    )

    assert payload["success"] is True
    assert payload["saved_count"] == 2
    assert payload["download_task"]["status"] == "completed"

    coverage = coverage_service.get_data_coverage(
        symbol,
        "SSE",
        "1m",
        start_date="2024-01-02T09:31:00",
        end_date="2024-01-02T09:32:00",
    )
    assert coverage["status"] == "covered"
    assert coverage["bar_count"] == 2


def test_date_only_intraday_coverage_ignores_non_trading_hours() -> None:
    symbol = f"D{uuid4().hex[:8]}"
    download_service.download_bars(
        symbol,
        "SSE",
        "1m",
        "2024-01-02",
        "2024-01-02",
        client=FakeBarClient(),
    )

    coverage = coverage_service.get_data_coverage(
        symbol,
        "SSE",
        "1m",
        start_date="2024-01-02",
        end_date="2024-01-02",
    )

    assert coverage["status"] == "covered"
    assert coverage["missing_ranges"] == []


def test_missing_coverage_reports_missing_range() -> None:
    symbol = f"M{uuid4().hex[:8]}"
    coverage = coverage_service.get_data_coverage(
        symbol,
        "SSE",
        "1m",
        start_date="2024-01-02",
        end_date="2024-01-03",
    )
    assert coverage["status"] == "missing"
    assert coverage["missing_ranges"]
