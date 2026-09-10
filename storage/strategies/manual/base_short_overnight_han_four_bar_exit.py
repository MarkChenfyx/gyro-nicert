from __future__ import annotations

from datetime import time
from typing import List

from vnpy_ctastrategy import (
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class BaseShortOvernightHanFourBarExitStrategy(CtaTemplate):
    """带一手底仓的日内减仓策略，加入四根反向突破回补。"""

    author = "LocalManual"

    fixed_size = 1
    trailpercent = 0.3
    exit_time = time(hour=14, minute=55)
    lookback_bars = 300
    long_only = 0
    short_only = 1
    trade_limit = 10
    reverse_confirm_bars = 4

    bars: List[BarData] = []

    day_open = 0.0
    day_high = 0.0
    day_low = 0.0
    day_close = 0.0

    intra_trade_high = 0.0
    intra_trade_low = 0.0
    long_stop = 0.0
    short_stop = 0.0
    intraday_trades_count = 0
    reverse_break_count = 0
    last_pos = 0

    parameters = [
        "fixed_size",
        "trailpercent",
        "lookback_bars",
        "long_only",
        "short_only",
        "trade_limit",
        "reverse_confirm_bars",
    ]
    variables = [
        "day_open",
        "day_high",
        "day_low",
        "day_close",
        "intra_trade_high",
        "intra_trade_low",
        "long_stop",
        "short_stop",
        "reverse_break_count",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        # 平台统一采用单位仓位；策略运行时也固定为一手底仓。
        self.fixed_size = 1
        self.reverse_confirm_bars = max(1, int(self.reverse_confirm_bars))
        self.bg = BarGenerator(self.on_bar)
        self.last_pos = 0
        self.bars = []

    def on_init(self):
        self.write_log("带底仓四根反向突破回补策略初始化完成")
        self.load_bar(self.lookback_bars + 1)

    def on_start(self):
        self.write_log("策略启动成功")

    def on_stop(self):
        self.write_log("策略已停止")

    def on_tick(self, tick: TickData):
        if time(9, 30) <= tick.datetime.time() <= time(15, 0):
            self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        self.cancel_all()
        self._update_bar_buffer(bar)

        if self._is_new_trading_day():
            self._handle_new_trading_day(bar)
        else:
            self._update_daily_prices(bar)

        # 计算突破区间时需要“当前 K 线 + 前 lookback_bars 根已完成 K 线”。
        if len(self.bars) < self.lookback_bars + 1:
            self.put_event()
            return

        if time(10, 0) < bar.datetime.time() < self.exit_time:
            self._execute_trading_logic(bar)

        self.put_event()

    def _update_bar_buffer(self, bar: BarData):
        self.bars.append(bar)
        if len(self.bars) > self.lookback_bars + 1:
            self.bars.pop(0)

    def _is_new_trading_day(self) -> bool:
        return len(self.bars) < 2 or self.bars[-2].datetime.date() != self.bars[-1].datetime.date()

    def _handle_new_trading_day(self, bar: BarData):
        self.day_open = bar.open_price
        self.day_high = bar.high_price
        self.day_low = bar.low_price
        self.day_close = bar.close_price
        self.intraday_trades_count = 0
        self.reverse_break_count = 0

    def _update_daily_prices(self, bar: BarData):
        self.day_high = max(self.day_high, bar.high_price)
        self.day_low = min(self.day_low, bar.low_price)
        self.day_close = bar.close_price

    def _execute_trading_logic(self, bar: BarData):
        # pos == fixed_size 表示仍持有一手底仓；pos < fixed_size 表示已卖出部分或全部底仓。
        if self.pos == self.fixed_size:
            self._process_base_position(bar)
        elif self.pos > self.fixed_size:
            self._manage_long_position(bar)
        else:
            self._manage_reduced_base_position(bar)

        self._update_trade_counter()

    def _process_base_position(self, bar: BarData):
        self.intra_trade_low = bar.low_price
        self.intra_trade_high = bar.high_price
        self.reverse_break_count = 0

        if not self.day_open:
            return

        completed_bars = self._get_completed_lookback_bars()
        lookback_low = min(item.low_price for item in completed_bars)

        is_short_enabled = not bool(self.long_only)
        if (
            bar.close_price < self.day_open
            and is_short_enabled
            and self._is_trade_allowed()
        ):
            # 从一手底仓卖出一手，仓位由 +1 变为 0；并非建立净空头。
            self.sell(lookback_low, self.fixed_size, stop=True, lock=True)

    def _manage_long_position(self, bar: BarData):
        self.intra_trade_high = max(self.intra_trade_high, bar.high_price)
        self.long_stop = self.intra_trade_high * (1 - self.trailpercent / 100)
        self.sell(self.long_stop, abs(self.pos - self.fixed_size), stop=True, lock=True)

    def _manage_reduced_base_position(self, bar: BarData):
        self.intra_trade_low = min(self.intra_trade_low, bar.low_price)
        self.short_stop = self.intra_trade_low * (1 + self.trailpercent / 100)

        completed_bars = self._get_completed_lookback_bars()
        reverse_breakout = bar.close_price > max(item.high_price for item in completed_bars)
        if reverse_breakout:
            self.reverse_break_count += 1
        else:
            self.reverse_break_count = 0

        if self.reverse_break_count >= self.reverse_confirm_bars:
            # 连续四根反向向上突破：回补到一手底仓。
            self.buy(
                bar.close_price * 1.01,
                abs(self.pos - self.fixed_size),
                lock=True,
            )
        else:
            # 在四根确认前，仍由移动止损保护已减掉的底仓。
            self.buy(
                self.short_stop,
                abs(self.pos - self.fixed_size),
                stop=True,
                lock=True,
            )

    def _get_completed_lookback_bars(self) -> List[BarData]:
        """返回当前 K 线之前的 lookback_bars 根 K 线，避免前视。"""
        return self.bars[-self.lookback_bars - 1:-1]

    def _is_trade_allowed(self) -> bool:
        return self.intraday_trades_count < self.trade_limit

    def _update_trade_counter(self):
        if self.last_pos != self.pos:
            self.intraday_trades_count += 1
        self.last_pos = self.pos

    def on_order(self, order: OrderData):
        pass

    def on_trade(self, trade: TradeData):
        self.put_event()
        self.write_log(
            f"策略成交: {self.strategy_name}, {trade.symbol}, "
            f"价格: {trade.price}, 方向: {trade.direction.value}, 持仓: {self.pos}"
        )

    def on_stop_order(self, stop_order: StopOrder):
        pass
