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


class OpenFilterReverseBreakoutStrategy(CtaTemplate):
    """开盘方向过滤、反向收盘确认和移动止损组合策略。"""

    author = "LocalManual"

    # 策略参数。
    lookback_window = 15
    trailing_stop_pct = 1.8
    price_offset_pct = 0.0
    fixed_size = 1

    # 1=启用开盘方向过滤，0=关闭。
    use_open_filter = 1
    # 连续多少根收盘价确认反向突破；0=关闭反向突破退出。
    reverse_confirm_bars = 2
    # 1=允许隔夜，0=14:55开始平仓且不再开仓。
    allow_overnight = 1

    day_open_price = 0.0
    breakout_high = 0.0
    breakout_low = 0.0
    entry_price = 0.0
    intra_trade_high = 0.0
    intra_trade_low = 0.0
    trailing_stop_price = 0.0
    reverse_break_count = 0

    parameters = [
        "lookback_window",
        "trailing_stop_pct",
        "use_open_filter",
        "reverse_confirm_bars",
        "allow_overnight",
        "price_offset_pct"
    ]

    variables = [
        "day_open_price",
        "breakout_high",
        "breakout_low",
        "entry_price",
        "intra_trade_high",
        "intra_trade_low",
        "trailing_stop_price",
        "reverse_break_count",
        "pos",
    ]

    def __init__(
        self,
        cta_engine,
        strategy_name: str,
        vt_symbol: str,
        setting: dict,
    ) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.fixed_size = 1
        self.lookback_window = max(2, int(self.lookback_window))
        self.trailing_stop_pct = max(0.01, float(self.trailing_stop_pct))
        self.use_open_filter = 1 if int(self.use_open_filter) else 0
        self.reverse_confirm_bars = max(0, int(self.reverse_confirm_bars))
        self.allow_overnight = 1 if int(self.allow_overnight) else 0

        self.bg = BarGenerator(self.on_bar)
        self.bar_history: list[BarData] = []
        self.current_trading_date = None

    def on_init(self) -> None:
        self.write_log("开盘过滤反向突破策略初始化")
        self.load_bar(self.lookback_window + 10)

    def on_start(self) -> None:
        self.write_log("开盘过滤反向突破策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("开盘过滤反向突破策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        bar_date = bar.datetime.date()
        if self.current_trading_date != bar_date:
            self.current_trading_date = bar_date
            self.day_open_price = bar.open_price

        # 先用历史缓存计算区间，再追加当前K线，确保没有前视。
        if len(self.bar_history) < self.lookback_window:
            self._append_bar(bar)
            self.put_event()
            return

        if not self.allow_overnight and bar.datetime.time() >= time(14, 55):
            self.reverse_break_count = 0
            if self.pos > 0:
                exit_price = bar.close_price * (1.0 - self.price_offset_pct / 100.0)
                self.sell(exit_price, abs(self.pos))
            elif self.pos < 0:
                exit_price = bar.close_price * (1.0 + self.price_offset_pct / 100.0)
                self.cover(exit_price, abs(self.pos))
            self._append_bar(bar)
            self.put_event()
            return

        recent_bars = self.bar_history[-self.lookback_window :]
        self.breakout_high = max(item.high_price for item in recent_bars)
        self.breakout_low = min(item.low_price for item in recent_bars)

        long_breakout = bar.close_price > self.breakout_high
        short_breakout = bar.close_price < self.breakout_low

        if self.pos == 0:
            self._handle_flat(bar, long_breakout, short_breakout)
        elif self.pos > 0:
            self._manage_long(bar, short_breakout)
        else:
            self._manage_short(bar, long_breakout)

        self._append_bar(bar)
        self.put_event()

    def _handle_flat(
        self,
        bar: BarData,
        long_breakout: bool,
        short_breakout: bool,
    ) -> None:
        self._reset_trade_state()

        allow_long = not self.use_open_filter or bar.close_price > self.day_open_price
        allow_short = not self.use_open_filter or bar.close_price < self.day_open_price

        if long_breakout and not short_breakout and allow_long:
            entry_price = bar.close_price * (1.0 + self.price_offset_pct / 100.0)
            self.buy(entry_price, self.fixed_size)
        elif short_breakout and not long_breakout and allow_short:
            entry_price = bar.close_price * (1.0 - self.price_offset_pct / 100.0)
            self.short(entry_price, self.fixed_size)

    def _manage_long(self, bar: BarData, reverse_breakout: bool) -> None:
        self.intra_trade_high = max(self.intra_trade_high, bar.high_price)
        self.trailing_stop_price = self.intra_trade_high * (
            1.0 - self.trailing_stop_pct / 100.0
        )

        if self.reverse_confirm_bars > 0 and reverse_breakout:
            self.reverse_break_count += 1
        else:
            self.reverse_break_count = 0

        if (
            self.reverse_confirm_bars > 0
            and self.reverse_break_count >= self.reverse_confirm_bars
        ):
            exit_price = bar.close_price * (1.0 - self.price_offset_pct / 100.0)
            self.sell(exit_price, abs(self.pos))
        else:
            self.sell(self.trailing_stop_price, abs(self.pos), stop=True)

    def _manage_short(self, bar: BarData, reverse_breakout: bool) -> None:
        if self.intra_trade_low <= 0:
            self.intra_trade_low = min(self.entry_price, bar.low_price)
        else:
            self.intra_trade_low = min(self.intra_trade_low, bar.low_price)
        self.trailing_stop_price = self.intra_trade_low * (
            1.0 + self.trailing_stop_pct / 100.0
        )

        if self.reverse_confirm_bars > 0 and reverse_breakout:
            self.reverse_break_count += 1
        else:
            self.reverse_break_count = 0

        if (
            self.reverse_confirm_bars > 0
            and self.reverse_break_count >= self.reverse_confirm_bars
        ):
            exit_price = bar.close_price * (1.0 + self.price_offset_pct / 100.0)
            self.cover(exit_price, abs(self.pos))
        else:
            self.cover(self.trailing_stop_price, abs(self.pos), stop=True)

    def _append_bar(self, bar: BarData) -> None:
        self.bar_history.append(bar)
        if len(self.bar_history) > self.lookback_window:
            self.bar_history.pop(0)

    def _reset_trade_state(self) -> None:
        self.entry_price = 0.0
        self.intra_trade_high = 0.0
        self.intra_trade_low = 0.0
        self.trailing_stop_price = 0.0
        self.reverse_break_count = 0

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if self.pos > 0:
            self.entry_price = trade.price
            self.intra_trade_high = trade.price
            self.intra_trade_low = 0.0
            self.trailing_stop_price = trade.price * (
                1.0 - self.trailing_stop_pct / 100.0
            )
            self.reverse_break_count = 0
        elif self.pos < 0:
            self.entry_price = trade.price
            self.intra_trade_high = 0.0
            self.intra_trade_low = trade.price
            self.trailing_stop_price = trade.price * (
                1.0 + self.trailing_stop_pct / 100.0
            )
            self.reverse_break_count = 0
        else:
            self._reset_trade_state()

        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
