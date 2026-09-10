from __future__ import annotations

from datetime import time

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class Simple60mDonchianLongStrategy(CtaTemplate):
    """Simple long-only 60-minute Donchian channel strategy."""

    author = "LocalManual"

    entry_window = 20
    exit_window = 10
    fixed_size = 1

    entry_high = 0.0
    exit_low = 0.0
    entry_price = 0.0

    parameters = ["entry_window", "exit_window"]
    variables = ["entry_high", "exit_low", "entry_price", "pos"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.entry_window = max(2, int(self.entry_window))
        self.exit_window = max(2, int(self.exit_window))

        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None

    def on_init(self) -> None:
        self.write_log("简单双通道只做多策略初始化")
        self.load_bar(max(self.entry_window, self.exit_window) + 20)

    def on_start(self) -> None:
        self.write_log("简单双通道只做多策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("简单双通道只做多策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        completed = self._update_60m_bucket(bar)
        if completed is not None:
            self._on_60m_bar(completed)

        self.put_event()

    def _on_60m_bar(self, bar: BarData) -> None:
        required = max(self.entry_window, self.exit_window)
        if len(self.history) < required:
            self._append_history(bar)
            return

        # 通道只由当前信号 K 线之前已经完成的 60 分钟 K 线构造。
        self.entry_high = max(
            item.high_price for item in self.history[-self.entry_window:]
        )
        self.exit_low = min(
            item.low_price for item in self.history[-self.exit_window:]
        )

        if self.pos == 0 and bar.close_price > self.entry_high:
            self.buy(bar.close_price * 1.01, self.fixed_size)
        elif self.pos > 0 and bar.close_price < self.exit_low:
            self.sell(bar.close_price * 0.99, abs(self.pos))

        self._append_history(bar)

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = max(self.entry_window, self.exit_window) + 10
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

        return (bar.datetime.date(), session, minute // 60), minute % 60

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
        if self.pos > 0:
            self.entry_price = trade.price
        else:
            self.entry_price = 0.0
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
