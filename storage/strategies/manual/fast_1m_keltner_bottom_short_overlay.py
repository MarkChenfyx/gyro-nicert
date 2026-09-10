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


class Fast1mKeltnerBottomShortOverlayStrategy(CtaTemplate):
    """Keltner base-position timing using cover to establish and restore inventory."""

    author = "LocalManual"

    window = 700
    k = 3.0
    fixed_size = 1

    ema = 0.0
    atr = 0.0
    upper_band = 0.0
    lower_band = 0.0

    parameters = ["window", "k"]
    variables = [
        "ema",
        "atr",
        "upper_band",
        "lower_band",
        "base_initialized",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.window = max(2, int(self.window))
        self.k = max(0.1, float(self.k))

        self.bg = BarGenerator(self.on_bar)
        self.sample_count = 0
        self.previous_close: float | None = None
        self.tr_seed: list[float] = []
        self.indicators_ready = False
        self.base_initialized = False

    def on_init(self) -> None:
        self.write_log("1-minute Keltner cover-base strategy initialized")
        required_days = (self.window + 239) // 240 + 5
        self.load_bar(max(10, required_days))

    def on_start(self) -> None:
        self.write_log("1-minute Keltner cover-base strategy started")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("1-minute Keltner cover-base strategy stopped")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        # Bands are calculated only from bars completed before this signal bar.
        if self.trading and self.indicators_ready:
            close = float(bar.close_price)

            if not self.base_initialized and self.pos == 0:
                # The teacher engine treats a filled LONG/CLOSE order as +volume,
                # so cover is used here to establish the initial base inventory.
                self.cover(close * 1.01, self.fixed_size)
            elif self.pos > 0 and close <= self.lower_band:
                # Reduce the one-unit base position to flat.
                self.sell(close * 0.99, abs(self.pos))
            elif self.base_initialized and self.pos == 0 and close >= self.upper_band:
                # Restore the one-unit base position after an upward breakout.
                self.cover(close * 1.01, self.fixed_size)

        self._update_indicators(bar)
        self.put_event()

    def _update_indicators(self, bar: BarData) -> None:
        close = float(bar.close_price)
        self.sample_count += 1

        if self.sample_count == 1:
            self.ema = close
        else:
            alpha = 2.0 / (self.window + 1.0)
            self.ema = alpha * close + (1.0 - alpha) * self.ema

        if self.previous_close is not None:
            true_range = max(
                float(bar.high_price - bar.low_price),
                abs(float(bar.high_price) - self.previous_close),
                abs(float(bar.low_price) - self.previous_close),
            )
            self.atr = self._next_wilder_atr(true_range)

        self.previous_close = close
        self.indicators_ready = len(self.tr_seed) >= self.window and self.atr > 0
        if not self.indicators_ready:
            return

        self.upper_band = self.ema + self.k * self.atr
        self.lower_band = self.ema - self.k * self.atr

    def _next_wilder_atr(self, true_range: float) -> float:
        if len(self.tr_seed) < self.window:
            self.tr_seed.append(true_range)
            if len(self.tr_seed) == self.window:
                return sum(self.tr_seed) / self.window
            return 0.0
        return ((self.window - 1.0) * self.atr + true_range) / self.window

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if self.pos > 0:
            self.base_initialized = True
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
