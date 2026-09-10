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


class Simple60mMomentumLongStrategy(CtaTemplate):
    """Simple long-only momentum strategy using completed 60-minute bars."""

    author = "LocalManual"

    momentum_window = 20
    entry_threshold_pct = 1.0
    exit_threshold_pct = 0.0
    fixed_size = 1

    momentum_pct = 0.0
    entry_price = 0.0

    parameters = [
        "momentum_window",
        "entry_threshold_pct",
        "exit_threshold_pct",
    ]
    variables = ["momentum_pct", "entry_price", "pos"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.momentum_window = max(2, int(self.momentum_window))

        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.minute_bucket: list[BarData] = []
        self.bucket_key = None

    def on_init(self) -> None:
        self.write_log("简单60分钟动量策略初始化")
        self.load_bar(self.momentum_window + 20)

    def on_start(self) -> None:
        self.write_log("简单60分钟动量策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("简单60分钟动量策略停止")
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
        if len(self.history) < self.momentum_window + 1:
            self._append_history(bar)
            return

        # 动量完全由当前信号 K 线之前已经完成的 K 线计算。
        latest_close = self.history[-1].close_price
        base_close = self.history[-self.momentum_window - 1].close_price
        if base_close > 0:
            self.momentum_pct = (latest_close / base_close - 1.0) * 100.0
        else:
            self.momentum_pct = 0.0

        if self.pos == 0 and self.momentum_pct > self.entry_threshold_pct:
            self.buy(bar.close_price * 1.01, self.fixed_size)
        elif self.pos > 0 and self.momentum_pct <= self.exit_threshold_pct:
            self.sell(bar.close_price * 0.99, abs(self.pos))

        self._append_history(bar)

    def _append_history(self, bar: BarData) -> None:
        self.history.append(bar)
        limit = self.momentum_window + 10
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
