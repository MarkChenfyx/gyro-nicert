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


class OvernightOnlyLongStrategy(CtaTemplate):
    """Hold one unit overnight and remain flat during the trading day."""

    author = "LocalManual"

    exit_delay_minutes = 1
    fixed_size = 1

    entry_hour = 14
    entry_minute = 55
    entry_end_minute = 58
    price_offset_pct = 0.02

    entry_date_text = ""

    parameters = ["exit_delay_minutes"]
    variables = ["entry_date_text", "pos"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.exit_delay_minutes = max(1, min(120, int(self.exit_delay_minutes)))
        self.bg = BarGenerator(self.on_bar)
        self.entry_date: date | None = None

    def on_init(self) -> None:
        self.write_log("隔夜持有策略初始化")
        self.load_bar(2)

    def on_start(self) -> None:
        self.write_log("隔夜持有策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("隔夜持有策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        if not self.trading:
            self.put_event()
            return

        bar_time = bar.datetime.time()
        close = float(bar.close_price)
        buy_price = close * (1.0 + self.price_offset_pct / 100.0)
        sell_price = close * (1.0 - self.price_offset_pct / 100.0)

        if self.pos > 0 and self._should_exit(bar):
            self.sell(sell_price, abs(self.pos))
        elif self.pos == 0 and time(self.entry_hour, self.entry_minute) <= bar_time <= time(
            self.entry_hour,
            self.entry_end_minute,
        ):
            self.buy(buy_price, self.fixed_size)

        self.put_event()

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
