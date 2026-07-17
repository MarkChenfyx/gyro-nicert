from datetime import time, datetime, timedelta

import numpy as np
from vnpy_ctastrategy import (
    ArrayManager,
    BarData,
    BarGenerator,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class Han123StrategyAtrHL(CtaTemplate):
    """"""

    author = "Your Name"

    fixed_size = 1
    trailpercent_high = 0.28
    trailpercent_low = 0.28
    exit_time = time(hour=14, minute=50)
    lookback_bars_high = 220
    lookback_bars_low = 100
    trade_limit = 10
    delay_time_high = 10
    delay_time_low = 10
    bars = []

    day_open = 0
    day_high = 0
    day_low = 0
    day_close = 0

    intra_trade_high = 0
    intra_trade_low = 0
    long_stop = 0
    short_stop = 0
    long_only = 0
    short_only = 0
    intraday_only = 0

    atr_period = 21
    atr_multiplier = 2

    parameters = [
        "fixed_size",
        "trailpercent_high",
        "trailpercent_low",
        "lookback_bars_high",
        "lookback_bars_low",
        "trade_limit",
        "delay_time_high",
        "delay_time_low",
        "long_only",
        "short_only",
        "intraday_only",
        "atr_period",
        "atr_multiplier",
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
        "trailpercent",
        "lookback_bars",
        "delay_time",
    ]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)

        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager()
        self.bars = []
        self.day_bar = []
        self.trailpercent = 0
        self.lookback_bars = self.lookback_bars_high
        self.delay_time = 0
        self.last_pos = 0
        self.intraday_trades_count = 0

    def on_init(self):
        """
        Callback when strategy is inited.
        """
        self.write_log("策略初始化")

    def on_start(self):
        """
        Callback when strategy is started.
        """
        self.write_log("策略启动")
        self.load_bar(20)

    def on_stop(self):
        """
        Callback when strategy is stopped.
        """
        self.write_log("策略停止")

    def on_tick(self, tick: TickData):
        """
        Callback of new tick data update.
        """
        tick_time = tick.datetime.time()
        if tick_time < time(9, 29) or tick_time > time(15, 15):
            return
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData):
        """
        Callback of new bar data update.
        """
        self.cancel_all()
        self.bars.append(bar)
        if len(self.bars) <= self.lookback_bars:
            return
        self.bars.pop(0)
        last_bar = self.bars[-2]

        if last_bar.datetime.date() != bar.datetime.date():
            self.day_bar.append(self.day_close)
            if len(self.day_bar) >= self.atr_period:
                self.day_bar.pop(0)
            atr_thresh = self.atr_multiplier / 100
            std_ratio = np.std(self.day_bar) / np.mean(self.day_bar)

            if std_ratio > atr_thresh:
                self.trailpercent = self.trailpercent_high
                self.lookback_bars = self.lookback_bars_high
                self.delay_time = self.delay_time_high
            else:
                self.trailpercent = self.trailpercent_low
                self.lookback_bars = self.lookback_bars_low
                self.delay_time = self.delay_time_low

            self.day_open = bar.open_price
            self.day_high = bar.high_price
            self.day_low = bar.low_price
            self.day_close = bar.close_price
            self.intraday_trades_count = 0
        else:
            self.day_high = max(self.day_high, bar.high_price)
            self.day_low = min(self.day_low, bar.low_price)
            self.day_close = bar.close_price

        trading_start = (datetime.combine(bar.datetime.date(), time(9, 30)) + timedelta(minutes=self.delay_time)).time()
        if bar.datetime.time() < self.exit_time and bar.datetime.time() > trading_start:
            if self.pos == 0:
                self.intra_trade_low = bar.low_price
                self.intra_trade_high = bar.high_price

                if self.day_open and self.intraday_trades_count <= self.trade_limit:
                    try:
                        lookback_high = max(b.high_price for b in self.bars[-self.lookback_bars :])
                        lookback_low = min(b.low_price for b in self.bars[-self.lookback_bars :])
                    except Exception:
                        return

                    if bar.close_price > self.day_open:
                        if not self.short_only:
                            self.buy(lookback_high, self.fixed_size, stop=True, lock=True)
                    elif bar.close_price < self.day_open:
                        if not self.long_only:
                            self.short(lookback_low, self.fixed_size, stop=True, lock=True)

            elif self.pos > 0:
                self.intra_trade_high = max(self.intra_trade_high, bar.high_price)
                self.long_stop = self.intra_trade_high * (1 - self.trailpercent / 100)
                self.sell(self.long_stop, abs(self.pos), stop=True, lock=True)

            elif self.pos < 0:
                self.intra_trade_low = min(self.intra_trade_low, bar.low_price)
                self.short_stop = self.intra_trade_low * (1 + self.trailpercent / 100)
                self.cover(self.short_stop, abs(self.pos), stop=True, lock=True)

            if self.last_pos != self.pos:
                self.intraday_trades_count += 1

            self.last_pos = self.pos
        elif self.intraday_only:
            if self.pos > 0:
                self.sell(bar.close_price * 0.99, abs(self.pos), lock=True)
            elif self.pos < 0:
                self.cover(bar.close_price * 1.01, abs(self.pos), lock=True)

        self.put_event()

    def on_order(self, order: OrderData):
        """
        Callback of new order data update.
        """
        pass

    def on_trade(self, trade: TradeData):
        """
        Callback of new trade data update.
        """
        self.put_event()
        msg = f"新成交：{self.strategy_name}, {trade.symbol}, {trade.price}, {trade.direction}, {trade.offset}, {self.pos}"
        self.send_email(msg)

    def on_stop_order(self, stop_order: StopOrder):
        """
        Callback of stop order update.
        """
        pass

