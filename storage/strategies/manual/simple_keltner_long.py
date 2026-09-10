from __future__ import annotations

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class SimpleKeltnerLongStrategy(CtaTemplate):
    """Unit-position, long-only Keltner breakout strategy."""

    author = "LocalManual"

    t_window = 20
    atr_multiplier = 2.0
    fixed_size = 1

    ema_value = 0.0
    atr_value = 0.0
    upper_band = 0.0
    lower_band = 0.0
    entry_price = 0.0

    parameters = ["t_window", "atr_multiplier"]
    variables = [
        "ema_value",
        "atr_value",
        "upper_band",
        "lower_band",
        "entry_price",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.t_window = max(2, int(self.t_window))
        self.atr_multiplier = max(0.1, float(self.atr_multiplier))

        self.bg = BarGenerator(self.on_bar)
        self.sample_count = 0
        self.previous_close: float | None = None
        self.true_range_seed: list[float] = []
        self.indicators_ready = False

    def on_init(self) -> None:
        self.write_log("简单 Keltner 只做多策略初始化")
        self.load_bar(self.t_window + 20)

    def on_start(self) -> None:
        self.write_log("简单 Keltner 只做多策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("简单 Keltner 只做多策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        # upper_band/lower_band 均由当前 K 线之前的数据计算，避免前视。
        if self.indicators_ready:
            if self.pos == 0 and bar.close_price >= self.upper_band:
                self.buy(bar.close_price * 1.01, self.fixed_size)
            elif self.pos > 0 and bar.close_price <= self.lower_band:
                self.sell(bar.close_price * 0.99, abs(self.pos))

        self._update_indicators(bar)
        self.put_event()

    def _update_indicators(self, bar: BarData) -> None:
        close = float(bar.close_price)
        self.sample_count += 1

        if self.sample_count == 1:
            self.ema_value = close
        else:
            ema_alpha = 2.0 / (self.t_window + 1.0)
            self.ema_value = (
                ema_alpha * close
                + (1.0 - ema_alpha) * self.ema_value
            )

        if self.previous_close is not None:
            true_range = max(
                float(bar.high_price - bar.low_price),
                abs(float(bar.high_price) - self.previous_close),
                abs(float(bar.low_price) - self.previous_close),
            )

            if len(self.true_range_seed) < self.t_window:
                self.true_range_seed.append(true_range)
                if len(self.true_range_seed) == self.t_window:
                    self.atr_value = sum(self.true_range_seed) / self.t_window
            else:
                self.atr_value = (
                    (self.t_window - 1.0) * self.atr_value
                    + true_range
                ) / self.t_window

        self.previous_close = close
        self.indicators_ready = (
            self.sample_count >= self.t_window
            and len(self.true_range_seed) >= self.t_window
            and self.atr_value > 0
        )

        if self.indicators_ready:
            width = self.atr_multiplier * self.atr_value
            self.upper_band = self.ema_value + width
            self.lower_band = self.ema_value - width

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
