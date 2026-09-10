from __future__ import annotations

from datetime import time

from vnpy.trader.constant import Offset
from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class TrendPullbackRelaunchStrategy(CtaTemplate):
    """Buy the first contracting pullback inside an established uptrend."""

    author = "LocalManual"

    fast_window = 12
    slow_window = 40
    impulse_window = 8
    pullback_window = 4
    atr_window = 14
    atr_multiple = 2.8
    cooldown_bars = 4
    time_stop_bars = 12
    fixed_size = 1

    fast_ma = 0.0
    slow_ma = 0.0
    atr_value = 0.0
    entry_price = 0.0
    highest_price = 0.0
    protective_stop = 0.0
    holding_bars = 0
    cooldown_remaining = 0

    parameters = [
        "fast_window",
        "slow_window",
        "impulse_window",
        "pullback_window",
        "atr_window",
        "atr_multiple",
        "cooldown_bars",
        "time_stop_bars",
    ]
    variables = [
        "fast_ma",
        "slow_ma",
        "atr_value",
        "entry_price",
        "highest_price",
        "protective_stop",
        "holding_bars",
        "cooldown_remaining",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.fixed_size = 1
        self.fast_window = max(2, int(self.fast_window))
        self.slow_window = max(self.fast_window + 2, int(self.slow_window))
        self.impulse_window = max(3, int(self.impulse_window))
        self.pullback_window = max(2, int(self.pullback_window))
        self.atr_window = max(2, int(self.atr_window))
        self.cooldown_bars = max(0, int(self.cooldown_bars))
        self.time_stop_bars = max(1, int(self.time_stop_bars))
        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None
        self.pending_stop = 0.0

    def on_init(self) -> None:
        self.write_log("趋势回撤二次启动策略初始化")
        self.load_bar(max(self.slow_window + 20, 90))

    def on_start(self) -> None:
        self.write_log("趋势回撤二次启动策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("趋势回撤二次启动策略停止")
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
        required = max(
            self.slow_window + 1,
            self.atr_window + 1,
            self.impulse_window + self.pullback_window,
        )
        if len(self.history) < required:
            self._append_history(bar)
            return

        closes = [item.close_price for item in self.history]
        self.fast_ma = sum(closes[-self.fast_window:]) / self.fast_window
        self.slow_ma = sum(closes[-self.slow_window:]) / self.slow_window
        previous_slow = (
            sum(closes[-self.slow_window - 1:-1]) / self.slow_window
        )
        self.atr_value = self._prior_atr()

        if self.pos > 0:
            self.holding_bars += 1
            prior_exit_low = min(
                item.low_price for item in self.history[-self.pullback_window:]
            )
            trend_failed = bar.close_price < self.slow_ma
            structure_failed = bar.close_price < prior_exit_low
            stale_trade = (
                self.holding_bars >= self.time_stop_bars
                and self.highest_price < self.entry_price + self.atr_value
            )
            if trend_failed or structure_failed or stale_trade:
                self.cancel_all()
                self.sell(bar.close_price * 0.99, abs(self.pos))
            else:
                self.highest_price = max(self.highest_price, bar.high_price)
                candidate = self.highest_price - self.atr_multiple * self.atr_value
                self.protective_stop = max(self.protective_stop, candidate)

        elif self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        elif self.atr_value > 0:
            pullback = self.history[-self.pullback_window:]
            impulse = self.history[
                -(self.impulse_window + self.pullback_window):-self.pullback_window
            ]
            impulse_move = max(x.high_price for x in impulse) - min(
                x.low_price for x in impulse
            )
            trend_ok = (
                self.fast_ma > self.slow_ma
                and self.slow_ma > previous_slow
                and bar.close_price > self.slow_ma
            )
            pullback_ok = (
                min(x.low_price for x in pullback) <= self.fast_ma
                and min(x.close_price for x in pullback) > self.slow_ma
            )
            impulse_volume = sum(x.volume for x in impulse) / len(impulse)
            pullback_volume = sum(x.volume for x in pullback) / len(pullback)
            volume_ok = (
                impulse_volume <= 0
                or pullback_volume <= 0
                or pullback_volume < impulse_volume
            )
            relaunch = (
                bar.close_price > self.fast_ma
                and bar.close_price > self.history[-1].high_price
            )
            range_ok = (
                bar.high_price - bar.low_price <= 3.0 * self.atr_value
            )
            if (
                trend_ok
                and pullback_ok
                and volume_ok
                and relaunch
                and range_ok
                and impulse_move >= 1.5 * self.atr_value
            ):
                self.pending_stop = min(x.low_price for x in pullback)
                self.buy(bar.close_price * 1.01, self.fixed_size)

        self._append_history(bar)

    def _prior_atr(self) -> float:
        values = []
        start = max(1, len(self.history) - self.atr_window)
        for index in range(start, len(self.history)):
            bar = self.history[index]
            previous_close = self.history[index - 1].close_price
            values.append(
                max(
                    bar.high_price - bar.low_price,
                    abs(bar.high_price - previous_close),
                    abs(bar.low_price - previous_close),
                )
            )
        return sum(values[-self.atr_window:]) / len(values[-self.atr_window:])

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = max(self.slow_window, self.atr_window) + self.impulse_window + 20
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
            minute = value.hour * 60 + value.minute - (9 * 60 + 31)
            session = "am"
        elif time(13, 1) <= value <= time(15, 0):
            minute = value.hour * 60 + value.minute - (13 * 60 + 1)
            session = "pm"
        else:
            return None
        return (bar.datetime.date(), session, minute // 60), minute % 60

    @staticmethod
    def _aggregate(bars: list[BarData]) -> BarData:
        first, last = bars[0], bars[-1]
        return BarData(
            symbol=first.symbol,
            exchange=first.exchange,
            datetime=last.datetime,
            gateway_name=first.gateway_name,
            interval=first.interval,
            open_price=first.open_price,
            high_price=max(x.high_price for x in bars),
            low_price=min(x.low_price for x in bars),
            close_price=last.close_price,
            volume=sum(x.volume for x in bars),
            turnover=sum(x.turnover for x in bars),
            open_interest=last.open_interest,
        )

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if trade.offset == Offset.OPEN:
            self.entry_price = trade.price
            self.highest_price = trade.price
            self.holding_bars = 0
            self.protective_stop = max(
                self.pending_stop or 0.0,
                trade.price - self.atr_multiple * self.atr_value,
            )
        elif trade.offset == Offset.CLOSE and self.pos == 0:
            self.entry_price = 0.0
            self.highest_price = 0.0
            self.protective_stop = 0.0
            self.holding_bars = 0
            self.cooldown_remaining = self.cooldown_bars
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
