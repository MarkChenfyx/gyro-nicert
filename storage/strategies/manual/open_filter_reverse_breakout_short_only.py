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


class OpenFilterReverseBreakoutShortOnlyStrategy(CtaTemplate):
    """开盘方向过滤、反向收盘确认和移动止损组合策略（只做空）。"""

    author = "LocalManual"

    # 对应 open_filter_reverse_breakout | 20260724_145605 的入池参数。
    lookback_window = 40
    trailing_stop_pct = 0.8
    use_open_filter = 1
    reverse_confirm_bars = 4
    allow_overnight = 1
    price_offset_pct = 0.02
    fixed_size = 1

    day_open_price = 0.0
    breakout_high = 0.0
    breakout_low = 0.0
    entry_price = 0.0
    intra_trade_low = 0.0
    trailing_stop_price = 0.0
    reverse_break_count = 0

    parameters = [
        "lookback_window",
        "trailing_stop_pct",
        "use_open_filter",
        "reverse_confirm_bars",
        "allow_overnight",
        "price_offset_pct",
    ]

    variables = [
        "day_open_price",
        "breakout_high",
        "breakout_low",
        "entry_price",
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
        self.write_log("只做空开盘过滤反向突破策略初始化")
        self.load_bar(self.lookback_window + 10)

    def on_start(self) -> None:
        self.write_log("只做空开盘过滤反向突破策略启动")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("只做空开盘过滤反向突破策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        bar_date = bar.datetime.date()
        if self.current_trading_date != bar_date:
            self.current_trading_date = bar_date
            self.day_open_price = bar.open_price

        # 只使用已经完成的历史 K 线计算 HH/LL，排除当前 K 线。
        if len(self.bar_history) < self.lookback_window:
            self._append_bar(bar)
            self.put_event()
            return

        recent_bars = self.bar_history[-self.lookback_window :]
        self.breakout_high = max(item.high_price for item in recent_bars)
        self.breakout_low = min(item.low_price for item in recent_bars)

        if not self.allow_overnight and bar.datetime.time() >= time(14, 55):
            self.reverse_break_count = 0
            if self.pos < 0:
                exit_price = bar.close_price * (1.0 + self.price_offset_pct / 100.0)
                self.cover(exit_price, abs(self.pos))
            self._append_bar(bar)
            self.put_event()
            return

        long_breakout = bar.close_price > self.breakout_high
        short_breakout = bar.close_price < self.breakout_low

        if self.pos == 0:
            self._handle_flat(bar, short_breakout)
        elif self.pos < 0:
            self._manage_short(bar, long_breakout)

        self._append_bar(bar)
        self.put_event()

    def _handle_flat(self, bar: BarData, short_breakout: bool) -> None:
        self._reset_trade_state()
        allow_short = not self.use_open_filter or bar.close_price < self.day_open_price
        if short_breakout and allow_short:
            entry_price = bar.close_price * (1.0 - self.price_offset_pct / 100.0)
            self.short(entry_price, self.fixed_size)

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
        self.intra_trade_low = 0.0
        self.trailing_stop_price = 0.0
        self.reverse_break_count = 0

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if self.pos < 0:
            self.entry_price = trade.price
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
