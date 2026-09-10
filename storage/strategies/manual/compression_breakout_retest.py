from __future__ import annotations

from datetime import time

from vnpy.trader.constant import Offset
from vnpy_ctastrategy import BarData, BarGenerator, CtaTemplate, OrderData, StopOrder, TickData, TradeData


class CompressionBreakoutRetestStrategy(CtaTemplate):
    """Wait for volatility compression, an upside break, and its first retest."""

    author = "LocalManual"

    compression_window = 8
    baseline_window = 24
    compression_ratio = 0.70
    breakout_window = 20
    retest_bars = 4
    exit_window = 10
    atr_window = 14
    atr_multiple = 2.8
    cooldown_bars = 4
    time_stop_bars = 12
    fixed_size = 1

    compression_score = 0.0
    compression_high = 0.0
    breakout_level = 0.0
    retest_age = 0
    retest_seen = 0
    atr_value = 0.0
    entry_price = 0.0
    highest_price = 0.0
    protective_stop = 0.0
    holding_bars = 0
    cooldown_remaining = 0

    parameters = [
        "compression_window", "baseline_window", "compression_ratio",
        "breakout_window", "retest_bars", "exit_window", "atr_window",
        "atr_multiple",
    ]
    variables = [
        "compression_score", "compression_high", "breakout_level",
        "retest_age", "retest_seen", "atr_value", "entry_price",
        "highest_price", "protective_stop", "holding_bars",
        "cooldown_remaining", "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.fixed_size = 1
        self.compression_window = max(3, int(self.compression_window))
        self.baseline_window = max(self.compression_window + 2, int(self.baseline_window))
        self.breakout_window = max(3, int(self.breakout_window))
        self.retest_bars = max(1, int(self.retest_bars))
        self.exit_window = max(2, int(self.exit_window))
        self.atr_window = max(2, int(self.atr_window))
        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None

    def on_init(self) -> None:
        self.write_log("压缩突破首次回踩策略初始化")
        self.load_bar(max(self.baseline_window + 30, 90))

    def on_start(self) -> None:
        self.write_log("压缩突破首次回踩策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("压缩突破首次回踩策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        if self.pos > 0 and self.protective_stop > 0:
            self.sell(self.protective_stop, abs(self.pos), stop=True)
        completed = self._update_60m_bucket(bar)
        if completed is not None:
            self._on_60m_bar(completed)
        self.put_event()

    def _on_60m_bar(self, bar: BarData) -> None:
        required = max(self.baseline_window + 1, self.breakout_window, self.exit_window, self.atr_window + 1)
        if len(self.history) < required:
            self._append_history(bar)
            return

        ranges = self._prior_true_ranges(self.baseline_window)
        recent = ranges[-self.compression_window:]
        recent_average = sum(recent) / len(recent)
        baseline_average = sum(ranges) / len(ranges)
        self.compression_score = recent_average / baseline_average if baseline_average > 0 else 1.0
        self.atr_value = sum(ranges[-self.atr_window:]) / len(ranges[-self.atr_window:])
        prior_high = max(x.high_price for x in self.history[-self.breakout_window:])
        exit_low = min(x.low_price for x in self.history[-self.exit_window:])

        if self.pos > 0:
            self.holding_bars += 1
            self.highest_price = max(self.highest_price, bar.high_price)
            self.protective_stop = max(
                self.protective_stop,
                self.highest_price - self.atr_multiple * self.atr_value,
            )
            stale_trade = (
                self.holding_bars >= self.time_stop_bars
                and self.highest_price < self.entry_price + self.atr_value
            )
            if bar.close_price < exit_low or stale_trade:
                self.cancel_all()
                self.sell(bar.close_price * 0.99, abs(self.pos))
        elif self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            self._clear_setup()
        else:
            compressed = self.compression_score <= self.compression_ratio
            if compressed and self.breakout_level == 0:
                self.compression_high = max(
                    x.high_price for x in self.history[-self.compression_window:]
                )

            if (
                self.breakout_level == 0
                and self.compression_high > 0
                and bar.close_price > max(self.compression_high, prior_high)
                and bar.high_price - bar.low_price <= 3.0 * self.atr_value
            ):
                self.breakout_level = max(self.compression_high, prior_high)
                self.retest_age = 0
                self.retest_seen = 0
            elif self.breakout_level > 0:
                self.retest_age += 1
                tolerance = 0.35 * self.atr_value
                if (
                    bar.low_price <= self.breakout_level + tolerance
                    and bar.close_price >= self.breakout_level
                ):
                    self.retest_seen = 1
                confirmed = (
                    self.retest_seen
                    and bar.close_price > self.breakout_level
                    and bar.close_price > self.history[-1].high_price
                )
                if confirmed:
                    self.buy(bar.close_price * 1.01, self.fixed_size)
                    self._clear_setup()
                elif self.retest_age >= self.retest_bars or bar.close_price < self.breakout_level - tolerance:
                    self._clear_setup()

        self._append_history(bar)

    def _clear_setup(self) -> None:
        self.compression_high = 0.0
        self.breakout_level = 0.0
        self.retest_age = 0
        self.retest_seen = 0

    def _prior_true_ranges(self, window: int) -> list[float]:
        values = []
        start = max(1, len(self.history) - window)
        for i in range(start, len(self.history)):
            bar = self.history[i]
            close = self.history[i - 1].close_price
            values.append(max(bar.high_price - bar.low_price, abs(bar.high_price - close), abs(bar.low_price - close)))
        return values

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = max(self.baseline_window, self.breakout_window, self.exit_window, self.atr_window) + 30
        if len(self.history) > limit:
            self.history.pop(0)

    def _update_60m_bucket(self, bar: BarData) -> BarData | None:
        slot = self._session_slot(bar)
        if slot is None:
            return None
        key, offset = slot
        if key != self.bucket_key:
            self.minute_bucket = []
            self.bucket_key = key
        if offset != len(self.minute_bucket):
            self.minute_bucket = []
            if offset != 0:
                return None
        self.minute_bucket.append(bar)
        if len(self.minute_bucket) != 60:
            return None
        output = self._aggregate(self.minute_bucket)
        self.minute_bucket = []
        return output

    @staticmethod
    def _session_slot(bar: BarData):
        value = bar.datetime.time().replace(tzinfo=None)
        if time(9, 31) <= value <= time(11, 30):
            minute = value.hour * 60 + value.minute - 571
            session = "am"
        elif time(13, 1) <= value <= time(15, 0):
            minute = value.hour * 60 + value.minute - 781
            session = "pm"
        else:
            return None
        return (bar.datetime.date(), session, minute // 60), minute % 60

    @staticmethod
    def _aggregate(bars: list[BarData]) -> BarData:
        first, last = bars[0], bars[-1]
        return BarData(symbol=first.symbol, exchange=first.exchange, datetime=last.datetime,
            gateway_name=first.gateway_name, interval=first.interval, open_price=first.open_price,
            high_price=max(x.high_price for x in bars), low_price=min(x.low_price for x in bars),
            close_price=last.close_price, volume=sum(x.volume for x in bars),
            turnover=sum(x.turnover for x in bars), open_interest=last.open_interest)

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if trade.offset == Offset.OPEN:
            self.entry_price = trade.price
            self.highest_price = trade.price
            self.protective_stop = trade.price - self.atr_multiple * self.atr_value
            self.holding_bars = 0
        elif trade.offset == Offset.CLOSE and self.pos == 0:
            self.entry_price = 0.0
            self.highest_price = 0.0
            self.protective_stop = 0.0
            self.holding_bars = 0
            self.cooldown_remaining = self.cooldown_bars
            self._clear_setup()
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
