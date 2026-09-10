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


def update_td_setup(
    closes: list[float],
    buy_count: int,
    sell_count: int,
    lookback: int = 4,
    setup_length: int = 9,
) -> tuple[int, int, bool, bool]:
    """Update the basic TD Setup count without Price Flip or Countdown.

    A falling sequence is a TD Buy Setup and a rising sequence is a
    TD Sell Setup. Equality breaks both sequences. Completion is emitted
    only on the exact setup-length bar, not on later extension bars.
    """
    if lookback < 1:
        raise ValueError("lookback must be at least 1")
    if setup_length < 1:
        raise ValueError("setup_length must be at least 1")
    if len(closes) <= lookback:
        return 0, 0, False, False

    current_close = closes[-1]
    reference_close = closes[-1 - lookback]

    if current_close < reference_close:
        next_buy_count = buy_count + 1
        next_sell_count = 0
    elif current_close > reference_close:
        next_buy_count = 0
        next_sell_count = sell_count + 1
    else:
        next_buy_count = 0
        next_sell_count = 0

    return (
        next_buy_count,
        next_sell_count,
        next_buy_count == setup_length,
        next_sell_count == setup_length,
    )


class BasicTdSequentialV1Strategy(CtaTemplate):
    """Minimal reversal strategy using only the basic TD Setup phase.

    Rules:
    - Nine consecutive closes below the close four bars earlier complete a
      TD Buy Setup and target a unit long position.
    - Nine consecutive closes above the close four bars earlier complete a
      TD Sell Setup and target a unit short position.
    - The strategy reverses only when the opposite setup completes.

    This deliberately excludes Price Flip, Setup Perfection, TD Countdown,
    trend filters, stops, adding, and position sizing overlays.
    """

    author = "LocalManual"

    fixed_size = 1
    lookback = 4
    setup_length = 9
    order_price_offset = 0.01

    buy_count = 0
    sell_count = 0
    buy_setup_completed = False
    sell_setup_completed = False
    last_signal = 0

    parameters = ["lookback", "setup_length"]
    variables = [
        "buy_count",
        "sell_count",
        "buy_setup_completed",
        "sell_setup_completed",
        "last_signal",
        "pos",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.fixed_size = 1
        self.lookback = max(1, int(self.lookback))
        self.setup_length = max(1, int(self.setup_length))
        self.bg = BarGenerator(self.on_bar)
        self.closes: list[float] = []

    def on_init(self) -> None:
        self.write_log("Basic TD Sequential V1 initialized")
        self.load_bar(self.lookback + self.setup_length + 5)

    def on_start(self) -> None:
        self.write_log("Basic TD Sequential V1 started")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("Basic TD Sequential V1 stopped")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()
        self.closes.append(float(bar.close_price))

        (
            self.buy_count,
            self.sell_count,
            self.buy_setup_completed,
            self.sell_setup_completed,
        ) = update_td_setup(
            closes=self.closes,
            buy_count=self.buy_count,
            sell_count=self.sell_count,
            lookback=self.lookback,
            setup_length=self.setup_length,
        )

        if self.buy_setup_completed:
            self.last_signal = 1
            self._target_long(bar.close_price)
        elif self.sell_setup_completed:
            self.last_signal = -1
            self._target_short(bar.close_price)

        history_limit = self.lookback + self.setup_length + 10
        if len(self.closes) > history_limit:
            self.closes.pop(0)
        self.put_event()

    def _target_long(self, close_price: float) -> None:
        buy_price = close_price * (1 + self.order_price_offset)
        sell_price = close_price * (1 - self.order_price_offset)
        if self.pos > 0:
            return
        if self.pos < 0:
            self.cover(buy_price, abs(self.pos))
        self.buy(buy_price, self.fixed_size)

    def _target_short(self, close_price: float) -> None:
        buy_price = close_price * (1 + self.order_price_offset)
        sell_price = close_price * (1 - self.order_price_offset)
        if self.pos < 0:
            return
        if self.pos > 0:
            self.sell(sell_price, abs(self.pos))
        self.short(sell_price, self.fixed_size)

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
