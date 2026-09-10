from __future__ import annotations

from datetime import date, time
from math import floor

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class EhprFilteredOvernightLongStrategy(CtaTemplate):
    """Hold overnight only when the executable late-day EHPR is historically high."""

    author = "LocalManual"

    lookback_days = 60
    entry_quantile = 0.8
    fixed_size = 1

    entry_hour = 14
    entry_minute = 55
    entry_end_minute = 58
    exit_delay_minutes = 1
    price_offset_pct = 0.02

    current_ehpr = 0.0
    ehpr_threshold = 0.0
    entry_signal_active = False
    entry_date_text = ""

    parameters = ["lookback_days", "entry_quantile"]
    variables = [
        "current_ehpr",
        "ehpr_threshold",
        "entry_signal_active",
        "entry_date_text",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.lookback_days = max(20, int(self.lookback_days))
        self.entry_quantile = min(0.99, max(0.5, float(self.entry_quantile)))

        self.bg = BarGenerator(self.on_bar)
        self.current_date: date | None = None
        self.day_high = 0.0
        self.signal_recorded = False
        self.ehpr_history: list[float] = []
        self.entry_date: date | None = None

    def on_init(self) -> None:
        self.write_log("EHPR筛选隔夜策略初始化")
        self.load_bar(self.lookback_days + 5)

    def on_start(self) -> None:
        self.write_log("EHPR筛选隔夜策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("EHPR筛选隔夜策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        self._update_trading_day(bar)

        bar_time = bar.datetime.time()
        close = float(bar.close_price)
        self.day_high = max(self.day_high, float(bar.high_price))

        if not self.signal_recorded and bar_time >= time(self.entry_hour, self.entry_minute):
            self._record_late_day_signal(close)

        if self.trading:
            buy_price = close * (1.0 + self.price_offset_pct / 100.0)
            sell_price = close * (1.0 - self.price_offset_pct / 100.0)

            if self.pos > 0 and self._should_exit(bar):
                self.sell(sell_price, abs(self.pos))
            elif (
                self.pos == 0
                and self.entry_signal_active
                and time(self.entry_hour, self.entry_minute) <= bar_time <= time(
                    self.entry_hour,
                    self.entry_end_minute,
                )
            ):
                self.buy(buy_price, self.fixed_size)

        self.put_event()

    def _update_trading_day(self, bar: BarData) -> None:
        bar_date = bar.datetime.date()
        if self.current_date == bar_date:
            return
        self.current_date = bar_date
        self.day_high = 0.0
        self.signal_recorded = False
        self.entry_signal_active = False
        self.current_ehpr = 0.0

    def _record_late_day_signal(self, close: float) -> None:
        self.current_ehpr = self.day_high / close - 1.0 if close > 0 else 0.0
        history = self.ehpr_history[-self.lookback_days :]
        if len(history) >= self.lookback_days:
            self.ehpr_threshold = self._quantile(history, self.entry_quantile)
            self.entry_signal_active = self.current_ehpr >= self.ehpr_threshold
        else:
            self.ehpr_threshold = 0.0
            self.entry_signal_active = False

        # Append only after evaluating the signal so the current day is excluded
        # from its own historical threshold.
        self.ehpr_history.append(self.current_ehpr)
        if len(self.ehpr_history) > self.lookback_days:
            self.ehpr_history.pop(0)
        self.signal_recorded = True

    @staticmethod
    def _quantile(values: list[float], quantile: float) -> float:
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = quantile * (len(ordered) - 1)
        lower_index = floor(position)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = position - lower_index
        return ordered[lower_index] * (1.0 - weight) + ordered[upper_index] * weight

    def _should_exit(self, bar: BarData) -> bool:
        if self.entry_date is None or bar.datetime.date() <= self.entry_date:
            return False
        total_minutes = 9 * 60 + 30 + self.exit_delay_minutes
        exit_time = time(total_minutes // 60, total_minutes % 60)
        return bar.datetime.time() >= exit_time

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if self.pos > 0:
            self.entry_date = trade.datetime.date()
            self.entry_date_text = self.entry_date.isoformat()
        else:
            self.entry_date = None
            self.entry_date_text = ""
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
