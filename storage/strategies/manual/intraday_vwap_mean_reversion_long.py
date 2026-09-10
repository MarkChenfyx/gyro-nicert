from __future__ import annotations

from datetime import date, time
from math import sqrt

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class IntradayVwapMeanReversionLongStrategy(CtaTemplate):
    """Buy below prior-bar session VWAP and exit as price reverts."""

    author = "LocalManual"

    min_bars = 20
    entry_k = 1.5
    exit_k = 0.0
    price_offset_pct = 0.02
    fixed_size = 1

    session_vwap = 0.0
    session_std = 0.0
    entry_level = 0.0
    exit_level = 0.0
    session_bars = 0

    parameters = ["min_bars", "entry_k", "exit_k", "price_offset_pct"]
    variables = [
        "session_vwap",
        "session_std",
        "entry_level",
        "exit_level",
        "session_bars",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.min_bars = max(5, min(120, int(self.min_bars)))
        self.entry_k = max(0.0, float(self.entry_k))
        self.exit_k = max(0.0, float(self.exit_k))
        self.price_offset_pct = max(0.0, float(self.price_offset_pct))

        self.bg = BarGenerator(self.on_bar)
        self.session_date: date | None = None
        self.sum_weight = 0.0
        self.sum_price_weight = 0.0
        self.sum_price_sq_weight = 0.0

    def on_init(self) -> None:
        self.write_log("Intraday VWAP mean reversion initialized")
        self.load_bar(2)

    def on_start(self) -> None:
        self.write_log("Intraday VWAP mean reversion started")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("Intraday VWAP mean reversion stopped")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        self._reset_session_if_needed(bar)

        if not self.trading:
            self.put_event()
            return

        bar_time = bar.datetime.time().replace(tzinfo=None)
        if bar_time >= time(14, 55):
            if self.pos > 0:
                self.sell(self._sell_price(bar.close_price), abs(self.pos))
            self._append_bar(bar)
            self.put_event()
            return

        # Levels are calculated before appending the current bar, so the signal
        # uses only completed earlier K-lines.
        levels_ready = self.session_bars >= self.min_bars and self.session_std > 0
        if levels_ready:
            self.entry_level = self.session_vwap - self.entry_k * self.session_std
            self.exit_level = self.session_vwap - self.exit_k * self.session_std

            if self.pos == 0 and bar.close_price <= self.entry_level:
                self.buy(self._buy_price(bar.close_price), self.fixed_size)
            elif self.pos > 0 and bar.close_price >= self.exit_level:
                self.sell(self._sell_price(bar.close_price), abs(self.pos))

        self._append_bar(bar)
        self.put_event()

    def _reset_session_if_needed(self, bar: BarData) -> None:
        bar_date = bar.datetime.date()
        if self.session_date == bar_date:
            return
        self.session_date = bar_date
        self.sum_weight = 0.0
        self.sum_price_weight = 0.0
        self.sum_price_sq_weight = 0.0
        self.session_bars = 0
        self.session_vwap = 0.0
        self.session_std = 0.0
        self.entry_level = 0.0
        self.exit_level = 0.0

    def _append_bar(self, bar: BarData) -> None:
        typical_price = (
            float(bar.high_price) + float(bar.low_price) + float(bar.close_price)
        ) / 3.0
        weight = max(float(bar.volume), 1.0)

        self.sum_weight += weight
        self.sum_price_weight += typical_price * weight
        self.sum_price_sq_weight += typical_price * typical_price * weight
        self.session_bars += 1

        self.session_vwap = self.sum_price_weight / self.sum_weight
        variance = (
            self.sum_price_sq_weight / self.sum_weight
            - self.session_vwap * self.session_vwap
        )
        self.session_std = sqrt(max(variance, 0.0))

    def _buy_price(self, close: float) -> float:
        return close * (1.0 + self.price_offset_pct / 100.0)

    def _sell_price(self, close: float) -> float:
        return close * (1.0 - self.price_offset_pct / 100.0)

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
