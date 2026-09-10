from __future__ import annotations

from datetime import date, time

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class OpeningRangeMeanReversionLongStrategy(CtaTemplate):
    """Buy weakness below the opening range and exit on a rebound."""

    author = "LocalManual"

    opening_minutes = 30
    entry_k = 0.75
    exit_k = 0.0
    price_offset_pct = 0.02
    fixed_size = 1

    opening_center = 0.0
    opening_width = 0.0
    entry_level = 0.0
    exit_level = 0.0
    session_bars = 0

    parameters = ["opening_minutes", "entry_k", "exit_k", "price_offset_pct"]
    variables = [
        "opening_center",
        "opening_width",
        "entry_level",
        "exit_level",
        "session_bars",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.opening_minutes = max(5, min(120, int(self.opening_minutes)))
        self.entry_k = max(0.0, float(self.entry_k))
        self.exit_k = max(0.0, float(self.exit_k))
        self.price_offset_pct = max(0.0, float(self.price_offset_pct))

        self.bg = BarGenerator(self.on_bar)
        self.session_date: date | None = None
        self.opening_high = 0.0
        self.opening_low = 0.0

    def on_init(self) -> None:
        self.write_log("Opening range mean reversion initialized")
        self.load_bar(2)

    def on_start(self) -> None:
        self.write_log("Opening range mean reversion started")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("Opening range mean reversion stopped")
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
            self.put_event()
            return

        if self.session_bars < self.opening_minutes:
            self._update_opening_range(bar)
            self.put_event()
            return

        # The opening range contains only completed earlier bars.
        if self.opening_width <= 0:
            self.put_event()
            return

        if self.pos == 0 and bar.close_price <= self.entry_level:
            self.buy(self._buy_price(bar.close_price), self.fixed_size)
        elif self.pos > 0 and bar.close_price >= self.exit_level:
            self.sell(self._sell_price(bar.close_price), abs(self.pos))

        self.put_event()

    def _reset_session_if_needed(self, bar: BarData) -> None:
        bar_date = bar.datetime.date()
        if self.session_date == bar_date:
            return
        self.session_date = bar_date
        self.session_bars = 0
        self.opening_high = 0.0
        self.opening_low = 0.0
        self.opening_center = 0.0
        self.opening_width = 0.0
        self.entry_level = 0.0
        self.exit_level = 0.0

    def _update_opening_range(self, bar: BarData) -> None:
        if self.session_bars == 0:
            self.opening_high = float(bar.high_price)
            self.opening_low = float(bar.low_price)
        else:
            self.opening_high = max(self.opening_high, float(bar.high_price))
            self.opening_low = min(self.opening_low, float(bar.low_price))

        self.session_bars += 1
        self.opening_width = self.opening_high - self.opening_low
        self.opening_center = (self.opening_high + self.opening_low) / 2.0
        self.entry_level = self.opening_center - self.entry_k * self.opening_width
        self.exit_level = self.opening_center - self.exit_k * self.opening_width

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
