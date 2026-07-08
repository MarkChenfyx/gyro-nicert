from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backtesting import run_backtest
from data_manager import market_repository


def _storage_snapshot() -> set[str]:
    root = Path(__file__).resolve().parents[1] / "storage"
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def test_run_backtest_mock_mode_returns_stable_result_without_storage_side_effects() -> None:
    before = _storage_snapshot()
    result = run_backtest(
        strategy_code="class DemoStrategy: pass",
        class_name="DemoStrategy",
        vt_symbol="510300.SSE",
        parameters={"fixed_size": 1},
        config={"mode": "mock", "capital": 100000},
    )
    after = _storage_snapshot()

    assert result["success"] is True
    assert result["metrics"]
    assert result["daily_results"]
    assert "trades" in result
    assert result["error"] is None
    assert after == before


REAL_STRATEGY_CODE = """
from vnpy_ctastrategy import CtaTemplate


class RealSmokeStrategy(CtaTemplate):
    author = "test"
    fixed_size = 1
    parameters = ["fixed_size"]
    variables = []

    def on_init(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_tick(self, tick):
        pass

    def on_bar(self, bar):
        pass
"""


def test_run_backtest_real_mode_reports_missing_local_data() -> None:
    symbol = f"Z{uuid4().hex[:8]}"
    result = run_backtest(
        strategy_code=REAL_STRATEGY_CODE,
        class_name="RealSmokeStrategy",
        vt_symbol=f"{symbol}.SSE",
        parameters={},
        config={"mode": "real", "interval": "1m", "start_date": "2024-01-02", "end_date": "2024-01-03"},
    )

    assert result["success"] is False
    assert result["metrics"] == {}
    assert result["daily_results"] == []
    assert result["trades"] == []
    assert "market data coverage" in result["error"]
    assert result["diagnostics"][0]["level"] == "error"
    assert result["diagnostics"][0]["missing_ranges"]
    assert "/api/data/download" in result["diagnostics"][0]["suggestion"]


def test_run_backtest_real_mode_uses_local_sqlite_bars() -> None:
    symbol = f"R{uuid4().hex[:8]}"
    market_repository.upsert_bars(
        symbol,
        "SSE",
        "1m",
        [
            {"datetime": "2024-01-02T09:31:00", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000},
            {"datetime": "2024-01-02T09:32:00", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1000},
            {"datetime": "2024-01-03T09:31:00", "open": 1.2, "high": 1.4, "low": 1.1, "close": 1.3, "volume": 1000},
        ],
    )
    before = _storage_snapshot()
    result = run_backtest(
        strategy_code=REAL_STRATEGY_CODE,
        class_name="RealSmokeStrategy",
        vt_symbol=f"{symbol}.SSE",
        parameters={"fixed_size": 1},
        config={
            "mode": "real",
            "interval": "1m",
            "start_date": "2024-01-02T09:31:00",
            "end_date": "2024-01-03T09:31:00",
            "capital": 100000,
        },
    )
    after = _storage_snapshot()

    assert result["success"] is True
    assert result["metrics"]
    assert result["daily_results"]
    assert result["error"] is None
    assert "local SQLite" in result["diagnostics"][1]["message"]
    assert after == before


def test_run_backtest_real_mode_accepts_date_only_intraday_range() -> None:
    symbol = f"D{uuid4().hex[:8]}"
    market_repository.upsert_bars(
        symbol,
        "SSE",
        "1m",
        [
            {"datetime": "2024-01-02T09:31:00", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000},
            {"datetime": "2024-01-02T15:00:00", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1000},
        ],
    )

    result = run_backtest(
        strategy_code=REAL_STRATEGY_CODE,
        class_name="RealSmokeStrategy",
        vt_symbol=f"{symbol}.SSE",
        parameters={"fixed_size": 1},
        config={
            "mode": "real",
            "interval": "1m",
            "start_date": "2024-01-02",
            "end_date": "2024-01-02",
            "capital": 100000,
        },
    )

    assert result["success"] is True
    assert result["error"] is None
    assert result["daily_results"]
