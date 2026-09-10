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


class Fast1mKeltnerDonchianLongStrategy(CtaTemplate):
    """Unit-position Keltner + Donchian long strategy on 1-minute bars."""

    author = "LocalManual"

    entry_window = 300
    exit_window = 300
    k = 2.0
    fixed_size = 1

    upper_band = 0.0
    lower_band = 0.0
    entry_atr = 0.0
    exit_atr = 0.0
    entry_price = 0.0

    parameters = ["entry_window", "exit_window", "k"]
    variables = [
        "upper_band",
        "lower_band",
        "entry_atr",
        "exit_atr",
        "entry_price",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.entry_window = max(2, int(self.entry_window))
        self.exit_window = max(2, int(self.exit_window))
        self.k = max(0.1, float(self.k))

        self.bg = BarGenerator(self.on_bar)
        self.history: list[BarData] = []
        self.sample_count = 0
        self.previous_close: float | None = None
        self.entry_ema = 0.0
        self.exit_ema = 0.0
        self.entry_tr_seed: list[float] = []
        self.exit_tr_seed: list[float] = []
        self.indicators_ready = False

    def on_init(self) -> None:
        self.write_log("一分钟 Keltner + Donchian 策略初始化")
        required_days = (max(self.entry_window, self.exit_window) + 239) // 240 + 5
        self.load_bar(max(10, required_days))

    def on_start(self) -> None:
        self.write_log("一分钟 Keltner + Donchian 策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("一分钟 Keltner + Donchian 策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        # Bands contain only completed bars before the current signal bar.
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
            self.entry_ema = close
            self.exit_ema = close
        else:
            entry_alpha = 2.0 / (self.entry_window + 1.0)
            exit_alpha = 2.0 / (self.exit_window + 1.0)
            self.entry_ema = entry_alpha * close + (1.0 - entry_alpha) * self.entry_ema
            self.exit_ema = exit_alpha * close + (1.0 - exit_alpha) * self.exit_ema

        if self.previous_close is not None:
            true_range = max(
                float(bar.high_price - bar.low_price),
                abs(float(bar.high_price) - self.previous_close),
                abs(float(bar.low_price) - self.previous_close),
            )
            self.entry_atr = self._next_wilder_atr(
                self.entry_atr,
                self.entry_tr_seed,
                true_range,
                self.entry_window,
            )
            self.exit_atr = self._next_wilder_atr(
                self.exit_atr,
                self.exit_tr_seed,
                true_range,
                self.exit_window,
            )

        self.previous_close = close
        self.history.append(bar)
        history_limit = max(self.entry_window, self.exit_window) + 1
        if len(self.history) > history_limit:
            self.history.pop(0)

        self.indicators_ready = (
            len(self.history) >= max(self.entry_window, self.exit_window)
            and len(self.entry_tr_seed) >= self.entry_window
            and len(self.exit_tr_seed) >= self.exit_window
            and self.entry_atr > 0
            and self.exit_atr > 0
        )
        if not self.indicators_ready:
            return

        donchian_upper = max(
            item.close_price for item in self.history[-self.entry_window:]
        )
        donchian_lower = min(
            item.close_price for item in self.history[-self.exit_window:]
        )
        keltner_upper = self.entry_ema + self.k * self.entry_atr
        keltner_lower = self.exit_ema - self.k * self.exit_atr

        self.upper_band = min(donchian_upper, keltner_upper)
        self.lower_band = max(donchian_lower, keltner_lower)

    @staticmethod
    def _next_wilder_atr(
        current_atr: float,
        seed: list[float],
        true_range: float,
        window: int,
    ) -> float:
        if len(seed) < window:
            seed.append(true_range)
            if len(seed) == window:
                return sum(seed) / window
            return 0.0
        return ((window - 1.0) * current_atr + true_range) / window

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
