from __future__ import annotations

from datetime import time
from math import ceil

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


class Simple30mDirectionalMomentumLongStrategy(CtaTemplate):
    """Long-only directional momentum strategy on completed 30-minute bars."""

    author = "LocalManual"

    signal_window = 5
    min_up_ratio_pct = 80.0
    min_return_pct = 0.3
    exit_down_bars = 2
    trailing_stop_pct = 1.0
    fixed_size = 1

    up_bars = 0
    up_ratio_pct = 0.0
    signal_return_pct = 0.0
    down_bars = 0
    entry_price = 0.0
    highest_price = 0.0
    trailing_stop_price = 0.0

    parameters = [
        "signal_window",
        "min_up_ratio_pct",
        "min_return_pct",
        "exit_down_bars",
        "trailing_stop_pct",
    ]
    variables = [
        "up_bars",
        "up_ratio_pct",
        "signal_return_pct",
        "down_bars",
        "entry_price",
        "highest_price",
        "trailing_stop_price",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.signal_window = max(2, int(self.signal_window))
        self.min_up_ratio_pct = min(
            100.0,
            max(0.0, float(self.min_up_ratio_pct)),
        )
        self.exit_down_bars = max(1, int(self.exit_down_bars))
        self.min_return_pct = max(0.0, float(self.min_return_pct))
        self.trailing_stop_pct = max(
            0.01,
            float(self.trailing_stop_pct),
        )

        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None

    def on_init(self) -> None:
        self.write_log("30-minute directional momentum strategy initialized")
        required = max(self.signal_window + 1, self.exit_down_bars + 1)
        self.load_bar(required + 20)

    def on_start(self) -> None:
        self.write_log("30-minute directional momentum strategy started")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("30-minute directional momentum strategy stopped")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        completed = self._update_30m_bucket(bar)
        if completed is not None:
            self._process_30m_bar(completed)
        elif self.pos > 0 and self.trailing_stop_price > 0:
            self.sell(self.trailing_stop_price, abs(self.pos), stop=True)

        self.put_event()

    def _process_30m_bar(self, bar: BarData) -> None:
        required = max(self.signal_window + 1, self.exit_down_bars + 1)
        if len(self.history) < required:
            self._append_history(bar)
            return

        # Signals use only completed bars before the current execution bar.
        signal_bars = self.history[-(self.signal_window + 1):]
        signal_closes = [float(item.close_price) for item in signal_bars]
        self.up_bars = sum(
            current > previous
            for previous, current in zip(signal_closes, signal_closes[1:])
        )
        self.up_ratio_pct = self.up_bars / self.signal_window * 100.0
        required_up_bars = ceil(
            self.signal_window * self.min_up_ratio_pct / 100.0
        )

        base_close = signal_closes[0]
        if base_close > 0:
            self.signal_return_pct = (
                signal_closes[-1] / base_close - 1.0
            ) * 100.0
        else:
            self.signal_return_pct = 0.0

        exit_bars = self.history[-(self.exit_down_bars + 1):]
        exit_closes = [float(item.close_price) for item in exit_bars]
        self.down_bars = sum(
            current < previous
            for previous, current in zip(exit_closes, exit_closes[1:])
        )
        consecutive_down = self.down_bars == self.exit_down_bars

        if self.pos == 0:
            if (
                self.up_bars >= required_up_bars
                and self.signal_return_pct >= self.min_return_pct
            ):
                self.buy(bar.close_price * 1.01, self.fixed_size)
        else:
            latest_signal_high = float(signal_bars[-1].high_price)
            self.highest_price = max(self.highest_price, latest_signal_high)
            candidate_stop = self.highest_price * (
                1.0 - self.trailing_stop_pct / 100.0
            )
            self.trailing_stop_price = max(
                self.trailing_stop_price,
                candidate_stop,
            )

            if consecutive_down:
                self.sell(bar.close_price * 0.99, abs(self.pos))
            elif self.trailing_stop_price > 0:
                self.sell(
                    self.trailing_stop_price,
                    abs(self.pos),
                    stop=True,
                )

        self._append_history(bar)

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = max(self.signal_window + 1, self.exit_down_bars + 1) + 10
        if len(self.history) > limit:
            self.history.pop(0)

    def _update_30m_bucket(self, bar: BarData) -> BarData | None:
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
        if len(self.minute_bucket) != 30:
            return None

        completed = self._aggregate(self.minute_bucket)
        self.minute_bucket = []
        return completed

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

        return (bar.datetime.date(), session, minute // 30), minute % 30

    @staticmethod
    def _aggregate(bars: list[BarData]) -> BarData:
        first = bars[0]
        last = bars[-1]

        return BarData(
            symbol=first.symbol,
            exchange=first.exchange,
            datetime=last.datetime,
            gateway_name=first.gateway_name,
            interval=first.interval,
            open_price=first.open_price,
            high_price=max(item.high_price for item in bars),
            low_price=min(item.low_price for item in bars),
            close_price=last.close_price,
            volume=sum(item.volume for item in bars),
            turnover=sum(item.turnover for item in bars),
            open_interest=last.open_interest,
        )

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if trade.offset == Offset.OPEN:
            self.entry_price = float(trade.price)
            self.highest_price = float(trade.price)
            self.trailing_stop_price = self.entry_price * (
                1.0 - self.trailing_stop_pct / 100.0
            )
        elif trade.offset == Offset.CLOSE and self.pos == 0:
            self.entry_price = 0.0
            self.highest_price = 0.0
            self.trailing_stop_price = 0.0
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
