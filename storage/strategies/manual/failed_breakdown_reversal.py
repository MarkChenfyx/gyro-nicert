from __future__ import annotations

from datetime import time

from vnpy.trader.constant import Offset
from vnpy_ctastrategy import BarData, BarGenerator, CtaTemplate, OrderData, StopOrder, TickData, TradeData


class FailedBreakdownReversalStrategy(CtaTemplate):
    """Buy a shallow downside channel break that is quickly reclaimed."""

    author = "LocalManual"

    trend_window = 40
    breakdown_window = 20
    reclaim_bars = 3
    atr_window = 14
    max_break_atr = 0.8
    stop_buffer_atr = 0.25
    atr_multiple = 2.6
    cooldown_bars = 4
    time_stop_bars = 12
    fixed_size = 1

    trend_ma = 0.0
    channel_low = 0.0
    atr_value = 0.0
    breakdown_level = 0.0
    breakdown_low = 0.0
    candidate_age = 0
    entry_price = 0.0
    highest_price = 0.0
    protective_stop = 0.0
    holding_bars = 0
    cooldown_remaining = 0

    parameters = [
        "trend_window", "breakdown_window", "reclaim_bars", "atr_window",
        "max_break_atr", "stop_buffer_atr", "atr_multiple", "cooldown_bars",
    ]
    variables = [
        "trend_ma", "channel_low", "atr_value", "breakdown_level",
        "breakdown_low", "candidate_age", "entry_price", "highest_price",
        "protective_stop", "holding_bars", "cooldown_remaining", "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.fixed_size = 1
        self.trend_window = max(3, int(self.trend_window))
        self.breakdown_window = max(3, int(self.breakdown_window))
        self.reclaim_bars = max(1, int(self.reclaim_bars))
        self.atr_window = max(2, int(self.atr_window))
        self.cooldown_bars = max(0, int(self.cooldown_bars))
        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None
        self.pending_stop = 0.0

    def on_init(self) -> None:
        self.write_log("向下假突破回收策略初始化")
        self.load_bar(max(self.trend_window + 20, 90))

    def on_start(self) -> None:
        self.write_log("向下假突破回收策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("向下假突破回收策略停止")
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
        required = max(self.trend_window + 1, self.breakdown_window, self.atr_window + 1)
        if len(self.history) < required:
            self._append_history(bar)
            return

        closes = [x.close_price for x in self.history]
        self.trend_ma = sum(closes[-self.trend_window:]) / self.trend_window
        previous_ma = sum(closes[-self.trend_window - 1:-1]) / self.trend_window
        self.channel_low = min(x.low_price for x in self.history[-self.breakdown_window:])
        self.atr_value = self._prior_atr()

        if self.pos > 0:
            self.holding_bars += 1
            self.highest_price = max(self.highest_price, bar.high_price)
            candidate = self.highest_price - self.atr_multiple * self.atr_value
            self.protective_stop = max(self.protective_stop, candidate)
            stale_trade = (
                self.holding_bars >= self.time_stop_bars
                and self.highest_price < self.entry_price + self.atr_value
            )
            if bar.close_price < self.trend_ma or stale_trade:
                self.cancel_all()
                self.sell(bar.close_price * 0.99, abs(self.pos))
        elif self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            self._clear_candidate()
        elif self.atr_value > 0:
            trend_ok = self.trend_ma >= previous_ma and bar.close_price > self.trend_ma
            penetration = self.channel_low - bar.low_price
            new_candidate = (
                trend_ok
                and bar.low_price < self.channel_low
                and penetration <= self.max_break_atr * self.atr_value
            )
            if new_candidate:
                self.breakdown_level = self.channel_low
                self.breakdown_low = bar.low_price
                self.candidate_age = 0

            if self.breakdown_level > 0:
                self.candidate_age += 1
                self.breakdown_low = min(self.breakdown_low, bar.low_price)
                bar_range = max(bar.high_price - bar.low_price, 1e-12)
                strong_close = (bar.close_price - bar.low_price) / bar_range >= 0.65
                reclaimed = bar.close_price > self.breakdown_level and strong_close
                if reclaimed and trend_ok:
                    self.pending_stop = (
                        self.breakdown_low - self.stop_buffer_atr * self.atr_value
                    )
                    self.buy(bar.close_price * 1.01, self.fixed_size)
                    self._clear_candidate()
                elif self.candidate_age >= self.reclaim_bars:
                    self._clear_candidate()

        self._append_history(bar)

    def _clear_candidate(self) -> None:
        self.breakdown_level = 0.0
        self.breakdown_low = 0.0
        self.candidate_age = 0

    def _prior_atr(self) -> float:
        values = []
        start = max(1, len(self.history) - self.atr_window)
        for i in range(start, len(self.history)):
            bar = self.history[i]
            close = self.history[i - 1].close_price
            values.append(max(bar.high_price - bar.low_price, abs(bar.high_price - close), abs(bar.low_price - close)))
        return sum(values[-self.atr_window:]) / len(values[-self.atr_window:])

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = max(self.trend_window, self.breakdown_window, self.atr_window) + 30
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
            self.protective_stop = self.pending_stop
            self.holding_bars = 0
        elif trade.offset == Offset.CLOSE and self.pos == 0:
            self.entry_price = 0.0
            self.highest_price = 0.0
            self.protective_stop = 0.0
            self.holding_bars = 0
            self.cooldown_remaining = self.cooldown_bars
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
