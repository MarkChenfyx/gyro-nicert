from __future__ import annotations

from datetime import datetime

from backend.backtesting.run import run_backtest
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData


STRATEGY_CODE = """
from vnpy_ctastrategy import CtaTemplate


class TeacherEngineSmokeStrategy(CtaTemplate):
    parameters = []
    variables = []

    entry_sent = False
    exit_sent = False

    def on_init(self):
        self.load_bar(1)

    def on_start(self):
        pass

    def on_stop(self):
        pass

    def on_bar(self, bar):
        if self.pos == 0 and not self.entry_sent:
            self.buy(bar.close_price + 1, 1)
            self.entry_sent = True
        elif self.pos > 0 and not self.exit_sent:
            self.sell(bar.close_price - 1, 1)
            self.exit_sent = True
"""


def _bars() -> list[BarData]:
    return [
        BarData(
            gateway_name="TEST",
            symbol="511380",
            exchange=Exchange.SSE,
            datetime=datetime(2026, 1, 5, hour),
            interval=Interval.MINUTE,
            open_price=price,
            high_price=price + 0.5,
            low_price=price - 0.5,
            close_price=price,
            volume=100,
        )
        for hour, price in ((9, 10.0), (10, 11.0), (11, 12.0), (12, 13.0))
    ]


def test_real_backtest_uses_teacher_engine_and_local_loader(monkeypatch) -> None:
    bars = _bars()
    monkeypatch.setattr(
        "backend.backtesting.run.coverage_service.get_data_coverage",
        lambda *args, **kwargs: {
            "status": "covered",
            "local_start": bars[0].datetime.isoformat(),
            "local_end": bars[-1].datetime.isoformat(),
            "missing_ranges": [],
        },
    )

    def fake_load(vt_symbol, interval, start, end):
        assert vt_symbol == "511380.SSE"
        assert interval == "1m"
        return [bar for bar in bars if start <= bar.datetime <= end]

    monkeypatch.setattr("backend.backtesting.run.local_data_provider.load_bar_data", fake_load)

    result = run_backtest(
        strategy_code=STRATEGY_CODE,
        class_name="TeacherEngineSmokeStrategy",
        vt_symbol="511380.SSE",
        parameters={},
        config={
            "mode": "real",
            "interval": "1m",
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
            "rate": 0,
            "slippage": 0,
            "size": 1,
            "pricetick": 0.001,
            "capital": 100000,
        },
    )

    assert result["success"] is True
    assert result["engine_name"] == "teacher_cta_backtesting_engine"
    assert result["engine_version"] == "teacher_backtesting_v1_local_sqlite"
    assert len(result["trades"]) == 2
    assert [trade["price"] for trade in result["trades"]] == [11.0, 12.0]
    assert result["metrics"]["total_net_pnl"] == 1.0
    assert any("本地 SQLite" in item["message"] for item in result["diagnostics"])


def test_tick_mode_fails_with_clear_local_data_message() -> None:
    result = run_backtest(
        strategy_code=STRATEGY_CODE,
        class_name="TeacherEngineSmokeStrategy",
        vt_symbol="511380.SSE",
        parameters={},
        config={"mode": "real", "data_mode": "tick", "interval": "1m"},
    )

    assert result["success"] is False
    assert "Tick" in str(result["error"])
