from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app
from data_manager import market_repository


def test_data_api_coverage_download_and_symbols(monkeypatch) -> None:
    client = TestClient(app)
    symbol = f"A{uuid4().hex[:8]}"

    market_repository.upsert_bars(
        symbol,
        "SSE",
        "1m",
        [
            {
                "datetime": "2024-01-02T09:31:00",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
                "turnover": 150,
            }
        ],
    )

    coverage = client.get(
        "/api/data/coverage",
        params={
            "symbol": symbol,
            "exchange": "SSE",
            "interval": "1m",
            "start_date": "2024-01-02T09:31:00",
            "end_date": "2024-01-02T09:31:00",
        },
    )
    assert coverage.status_code == 200
    assert coverage.json()["status"] == "covered"

    def fake_download(symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> dict:
        return {
            "success": True,
            "download_task": {"download_task_id": "download_test", "status": "completed"},
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "source": "rqdata",
            "bar_count": 1,
            "saved_count": 1,
            "coverage": {},
            "error": None,
        }

    monkeypatch.setattr("backend.api.data_api.download_service.download_bars", fake_download)
    downloaded = client.post(
        "/api/data/download",
        json={
            "symbol": symbol,
            "exchange": "SSE",
            "interval": "1m",
            "start_date": "2024-01-02",
            "end_date": "2024-01-02",
        },
    )
    assert downloaded.status_code == 200
    assert downloaded.json()["success"] is True

    symbols = client.get("/api/data/symbols")
    assert symbols.status_code == 200
    assert any(item["symbol"] == symbol for item in symbols.json()["items"])
