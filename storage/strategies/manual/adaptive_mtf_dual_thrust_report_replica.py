"""Adaptive multi-timeframe Dual Thrust strategy for vn.py bar backtesting.

The implementation is deliberately self-contained and causal: all signals use
only finished 1m/30m/60m bars, and all submitted orders are first executable
on the next minute bar in vn.py's bar-mode engine.
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, time
from typing import Deque

from vnpy.trader.constant import Offset
from vnpy_ctastrategy import (
    BarData,
    CtaTemplate,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)


class AdaptiveMtfDualThrustReportReplicaStrategy(CtaTemplate):
    """Platform-compliant replica of the report's research strategy semantics."""

    author = "Codex"

    # Position and Dual Thrust entry
    fixed_size = 1
    k1 = 1.4
    range_cap_pct = 0.3
    trade_limit_per_day = 1
    entry_cutoff_hour = 14
    entry_cutoff_minute = 50

    # Stop calculation
    atr_window_minutes = 20
    atr_multiplier = 10.0
    fallback_trail_pct = 0.2

    # Structure stop
    structure_window_minutes = 30
    structure_break_confirm_bars = 1
    structure_break_buffer = 0.0
    use_pre_structure_atr_trail = 1

    # Adaptive volatility state and trend permission
    adaptive_entry_gate = 1
    volatility_state_window_bars = 6
    high_vol_enter_count = 3
    high_vol_exit_count = 1
    volatility_history_sessions = 60
    high_volatility_percentile = 0.80
    trend_ma_bars = 8

    # Input data convention
    morning_start = time(hour=9, minute=32)
    morning_end = time(hour=11, minute=30)
    afternoon_start = time(hour=13, minute=1)
    afternoon_end = time(hour=15, minute=0)

    # Exposed state
    day_open = 0.0
    day_range = 0.0
    long_entry = 0.0
    day_high = 0.0
    trades_today = 0
    atr_value = 0.0
    entry_atr = 0.0
    intra_trade_high = 0.0
    atr_stop = 0.0
    emergency_stop = 0.0
    structure_low = 0.0
    structure_armed = 0
    structure_break_streak = 0
    high_volatility_state = 0
    trend_30m_up = 0
    trend_30m_down = 0
    trend_60m_up = 0
    volatility_threshold = 0.0
    entry_gate_mode = ""
    exit_reason = ""
    confirmed_structure_count = 0
    structure_break_signals = 0

    parameters = [
        "k1",
        "range_cap_pct",
        "trade_limit_per_day",
        "entry_cutoff_hour",
        "entry_cutoff_minute",
        "atr_window_minutes",
        "atr_multiplier",
        "fallback_trail_pct",
        "structure_window_minutes",
        "structure_break_confirm_bars",
        "structure_break_buffer",
        "use_pre_structure_atr_trail",
        "adaptive_entry_gate",
        "volatility_state_window_bars",
        "high_vol_enter_count",
        "high_vol_exit_count",
        "volatility_history_sessions",
        "high_volatility_percentile",
        "trend_ma_bars",
    ]

    variables = [
        "day_open",
        "day_range",
        "long_entry",
        "day_high",
        "trades_today",
        "atr_value",
        "entry_atr",
        "intra_trade_high",
        "atr_stop",
        "emergency_stop",
        "structure_low",
        "structure_armed",
        "structure_break_streak",
        "high_volatility_state",
        "trend_30m_up",
        "trend_30m_down",
        "trend_60m_up",
        "volatility_threshold",
        "entry_gate_mode",
        "exit_reason",
        "confirmed_structure_count",
        "structure_break_signals",
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

        # 平台统一采用单位仓位，禁止被 setting 覆盖。
        self.fixed_size = 1
        self._entry_cutoff = time(
            hour=max(0, min(23, int(self.entry_cutoff_hour))),
            minute=max(0, min(59, int(self.entry_cutoff_minute))),
        )

        self.current_date: date | None = None
        self.previous_day_high = 0.0
        self.previous_day_low = 0.0
        self.current_day_low = 0.0

        self._prior_close: float | None = None
        self._tr_values: Deque[float] = deque(
            maxlen=max(int(self.atr_window_minutes), 2)
        )
        self._entry_datetime: datetime | None = None
        self._pending_entry_atr = 0.0
        self._pending_entry_mode = ""

        self._aggregation_30m: list[BarData] = []
        self._aggregation_60m: list[BarData] = []
        self._aggregation_30m_key: tuple[date, str] | None = None
        self._aggregation_60m_key: tuple[date, str] | None = None

        self._structure_bars: Deque[BarData] = deque(maxlen=3)
        # The research source compares the current close with an SMA(8) that
        # includes that same close.  Algebraically, this is exactly equivalent
        # to comparing it with the mean of the preceding 7 closes.  Store only
        # those preceding closes so the platform's no-current-bar rule remains
        # explicit while the trend signal matches the report implementation.
        prior_trend_bars = max(int(self.trend_ma_bars) - 1, 1)
        self._trend_30m_closes: Deque[float] = deque(maxlen=prior_trend_bars)
        self._trend_60m_closes: Deque[float] = deque(maxlen=prior_trend_bars)

        self._current_session_volatilities: list[float] = []
        self._volatility_history: Deque[list[float]] = deque(
            maxlen=max(int(self.volatility_history_sessions), 1)
        )
        self._high_vol_flags: Deque[bool] = deque(
            maxlen=max(int(self.volatility_state_window_bars), 1)
        )

    @staticmethod
    def _plain_time(dt: datetime) -> time:
        value = dt.time()
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    def _session_info(
        self,
        dt: datetime,
    ) -> tuple[tuple[date, str], int] | None:
        value = self._plain_time(dt)

        if self.morning_start <= value <= self.morning_end:
            index = (value.hour * 60 + value.minute) - (9 * 60 + 32)
            return (dt.date(), "morning"), index

        if self.afternoon_start <= value <= self.afternoon_end:
            index = (value.hour * 60 + value.minute) - (13 * 60 + 1)
            return (dt.date(), "afternoon"), index

        return None

    def _regular_session(self, dt: datetime) -> bool:
        return self._session_info(dt) is not None

    def _update_atr(self, bar: BarData) -> float:
        """使用当前 K 线以前的真实波幅计算 ATR。"""

        high = float(bar.high_price)
        low = float(bar.low_price)

        if self._prior_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self._prior_close),
                abs(low - self._prior_close),
            )

        window = max(int(self.atr_window_minutes), 2)

        # 此时尚未加入当前 K 线，避免滚动指标包含当前 K 线。
        if len(self._tr_values) < window:
            self.atr_value = 0.0
        else:
            self.atr_value = float(
                sum(self._tr_values) / len(self._tr_values)
            )

        self._prior_close = float(bar.close_price)
        self._tr_values.append(max(true_range, 0.0))

        return self.atr_value

    def _roll_to_new_day(self, bar: BarData) -> None:
        bar_date = bar.datetime.date()

        if self.current_date == bar_date:
            return

        if self.current_date is not None:
            self.previous_day_high = self.day_high
            self.previous_day_low = self.current_day_low
            self._volatility_history.append(
                self._current_session_volatilities
            )

        if self.previous_day_high > 0 and self.previous_day_low > 0:
            raw_range = max(
                self.previous_day_high - self.previous_day_low,
                0.0,
            )
            capped_range = (
                max(float(self.range_cap_pct), 0.0)
                / 100.0
                * self.previous_day_low
            )
            self.day_range = min(raw_range, capped_range)
        else:
            self.day_range = 0.0

        self.current_date = bar_date
        self.day_open = float(bar.open_price)

        if self.day_range > 0:
            self.long_entry = (
                self.day_open
                + float(self.k1) * self.day_range
            )
        else:
            self.long_entry = 0.0

        self.day_high = float(bar.high_price)
        self.current_day_low = float(bar.low_price)
        self.trades_today = 0
        self._current_session_volatilities = []
        self.volatility_threshold = self._percentile_of_prior_sessions()
        self._pending_entry_mode = ""
        self.exit_reason = ""

    def _percentile_of_prior_sessions(self) -> float:
        observations = [
            item
            for session in self._volatility_history
            for item in session
        ]

        if not observations:
            return 0.0

        # 线性插值分位数，避免依赖 numpy。
        ordered = sorted(float(item) for item in observations)
        percentile = max(
            0.0,
            min(1.0, float(self.high_volatility_percentile)),
        )
        position = (len(ordered) - 1) * percentile
        lower_index = int(position)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = position - lower_index

        return (
            ordered[lower_index] * (1.0 - weight)
            + ordered[upper_index] * weight
        )

    def _make_aggregate_bar(
        self,
        bars: list[BarData],
    ) -> BarData:
        first = bars[0]
        last = bars[-1]

        return BarData(
            symbol=first.symbol,
            exchange=first.exchange,
            datetime=first.datetime,
            gateway_name=first.gateway_name,
            interval=first.interval,
            open_price=float(first.open_price),
            high_price=max(
                float(item.high_price) for item in bars
            ),
            low_price=min(
                float(item.low_price) for item in bars
            ),
            close_price=float(last.close_price),
            volume=sum(
                float(item.volume) for item in bars
            ),
            turnover=sum(
                float(item.turnover) for item in bars
            ),
            open_interest=float(last.open_interest),
        )

    def _update_aggregate(
        self,
        bar: BarData,
        window: int,
    ) -> BarData | None:
        info = self._session_info(bar.datetime)

        if info is None:
            return None

        session_key, minute_index = info

        if window == 30:
            collection = self._aggregation_30m
            key = self._aggregation_30m_key
        else:
            collection = self._aggregation_60m
            key = self._aggregation_60m_key

        if key != session_key:
            # 上午残留不能与下午数据拼接。
            collection.clear()
            key = session_key

            if window == 30:
                self._aggregation_30m_key = key
            else:
                self._aggregation_60m_key = key

        expected = len(collection)

        if minute_index % window != expected:
            collection.clear()

            if minute_index % window != 0:
                return None

        collection.append(bar)

        if session_key[1] == "morning":
            session_end = self.morning_end
        else:
            session_end = self.afternoon_end

        complete = len(collection) == window

        # 保留研究回测中上午最后一个 59 分钟的 60m 残段。
        usable_residue = (
            window == 60
            and self._plain_time(bar.datetime) == session_end
            and len(collection) >= 30
        )

        if not complete and not usable_residue:
            return None

        output = self._make_aggregate_bar(collection)
        collection.clear()

        return output

    def _entry_permission(self) -> tuple[bool, str]:
        if not bool(self.adaptive_entry_gate):
            return True, "ungated"

        if self.high_volatility_state:
            allowed = (
                bool(self.trend_60m_up)
                and not bool(self.trend_30m_down)
            )
            return allowed, "high_vol_60m"

        return bool(self.trend_30m_up), "normal_vol_30m"

    def _update_30m_state(self, bar: BarData) -> bool:
        """更新趋势、波动状态及结构，返回结构破位信号。"""

        close = float(bar.close_price)
        trend_window = max(int(self.trend_ma_bars) - 1, 1)

        # 先用历史窗口计算，再加入当前 30m K 线。
        if len(self._trend_30m_closes) >= trend_window:
            moving_average = float(
                sum(self._trend_30m_closes)
                / len(self._trend_30m_closes)
            )
            self.trend_30m_up = int(close > moving_average)
            self.trend_30m_down = int(close < moving_average)

        self._trend_30m_closes.append(close)

        if self.atr_value > 0 and close > 0:
            volatility_ratio = self.atr_value / close
        else:
            volatility_ratio = 0.0

        if volatility_ratio > 0:
            self._current_session_volatilities.append(
                volatility_ratio
            )

        high_volatility_bar = bool(
            self.volatility_threshold > 0
            and volatility_ratio > self.volatility_threshold
        )
        self._high_vol_flags.append(high_volatility_bar)

        state_window = max(
            int(self.volatility_state_window_bars),
            1,
        )

        if len(self._high_vol_flags) >= state_window:
            high_count = sum(self._high_vol_flags)

            if (
                not self.high_volatility_state
                and high_count >= int(self.high_vol_enter_count)
            ):
                self.high_volatility_state = 1
            elif (
                self.high_volatility_state
                and high_count <= int(self.high_vol_exit_count)
            ):
                self.high_volatility_state = 0

        if self.pos <= 0:
            self._structure_bars.clear()
            self.structure_break_streak = 0
            return False

        structure_break = False

        if self.structure_armed and self.structure_low > 0:
            break_level = self.structure_low * (
                1.0 - float(self.structure_break_buffer)
            )

            if close < break_level:
                self.structure_break_streak += 1
            else:
                self.structure_break_streak = 0

            if self.structure_break_streak >= max(
                int(self.structure_break_confirm_bars),
                1,
            ):
                structure_break = True

        self._structure_bars.append(bar)

        if (
            len(self._structure_bars) < 3
            or self._entry_datetime is None
        ):
            return structure_break

        left, pivot, right = self._structure_bars
        pivot_low = float(pivot.low_price)
        pivot_after_entry = (
            pivot.datetime > self._entry_datetime
        )
        is_pivot = (
            pivot_low < float(left.low_price)
            and pivot_low <= float(right.low_price)
        )
        rebound = float(right.close_price) > pivot_low

        if is_pivot and pivot_after_entry and rebound:
            if (
                self.structure_low <= 0
                or pivot_low > self.structure_low
            ):
                self.structure_low = pivot_low
                self.structure_armed = 1
                self.structure_break_streak = 0
                self.confirmed_structure_count += 1

        return structure_break

    def _update_60m_trend(self, bar: BarData) -> None:
        close = float(bar.close_price)
        trend_window = max(int(self.trend_ma_bars) - 1, 1)

        # 先用历史窗口计算，再加入当前 60m K 线。
        if len(self._trend_60m_closes) >= trend_window:
            moving_average = float(
                sum(self._trend_60m_closes)
                / len(self._trend_60m_closes)
            )
            self.trend_60m_up = int(close > moving_average)

        self._trend_60m_closes.append(close)

    def _manage_position(self, bar: BarData) -> None:
        self.intra_trade_high = max(
            self.intra_trade_high,
            float(bar.high_price),
        )

        if self.structure_armed:
            if self.emergency_stop > 0:
                self.sell(
                    self.emergency_stop,
                    abs(self.pos),
                    stop=True,
                )
            return

        protection_stop = self.emergency_stop

        if bool(self.use_pre_structure_atr_trail):
            reference_atr = max(
                self.atr_value,
                self.entry_atr,
            )

            if reference_atr > 0:
                candidate = (
                    self.intra_trade_high
                    - float(self.atr_multiplier) * reference_atr
                )
            else:
                candidate = self.intra_trade_high * (
                    1.0
                    - float(self.fallback_trail_pct) / 100.0
                )

            if self.atr_stop > 0:
                self.atr_stop = max(
                    self.atr_stop,
                    candidate,
                )
            else:
                self.atr_stop = candidate

            protection_stop = max(
                protection_stop,
                self.atr_stop,
            )

        if protection_stop > 0:
            self.sell(
                protection_stop,
                abs(self.pos),
                stop=True,
            )

    def _reset_position_state(self) -> None:
        self.entry_atr = 0.0
        self.intra_trade_high = 0.0
        self.atr_stop = 0.0
        self.emergency_stop = 0.0
        self.structure_low = 0.0
        self.structure_armed = 0
        self.structure_break_streak = 0
        self._structure_bars.clear()
        self._entry_datetime = None

    def on_init(self) -> None:
        self.write_log(
            f"{self.strategy_name} initialized"
        )

    def on_start(self) -> None:
        self.write_log(
            f"{self.strategy_name} started"
        )
        self.put_event()

    def on_stop(self) -> None:
        self.write_log(
            f"{self.strategy_name} stopped"
        )
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        # 当前版本用于分钟 K 线回测。
        if not self._regular_session(tick.datetime):
            return

    def on_bar(self, bar: BarData) -> None:
        if not self._regular_session(bar.datetime):
            return

        # 上一分钟提交的订单已经由回测引擎撮合。
        self.cancel_all()

        self._roll_to_new_day(bar)
        self._update_atr(bar)

        self.day_high = max(
            self.day_high,
            float(bar.high_price),
        )
        self.current_day_low = min(
            self.current_day_low,
            float(bar.low_price),
        )

        if self.pos > 0:
            self._manage_position(bar)

        elif (
            self.long_entry > 0
            and self._plain_time(bar.datetime)
            < self._entry_cutoff
        ):
            allowed, mode = self._entry_permission()

            if (
                allowed
                and self.trades_today
                < int(self.trade_limit_per_day)
            ):
                self._pending_entry_atr = self.atr_value
                self._pending_entry_mode = mode

                stop_price = max(
                    self.day_high,
                    self.long_entry,
                )

                # 开仓数量必须严格使用 self.fixed_size。
                self.buy(
                    stop_price,
                    self.fixed_size,
                    stop=True,
                )

        completed_30m = self._update_aggregate(
            bar,
            30,
        )

        if completed_30m is not None:
            structure_break = self._update_30m_state(
                completed_30m
            )

            if structure_break and self.pos > 0:
                # 当前完整 30m K 线确认破位，下一分钟退出。
                self.cancel_all()
                self.sell(
                    0.0,
                    abs(self.pos),
                )
                self.structure_break_signals += 1
                self.exit_reason = "30m_structure_break"

        completed_60m = self._update_aggregate(
            bar,
            60,
        )

        if completed_60m is not None:
            self._update_60m_trend(
                completed_60m
            )

        self.put_event()

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        if trade.offset == Offset.OPEN:
            self.trades_today += 1
            self.entry_atr = self._pending_entry_atr
            self.intra_trade_high = float(trade.price)
            self.atr_stop = 0.0
            self.emergency_stop = max(
                0.0,
                float(trade.price)
                - float(self.atr_multiplier) * self.entry_atr,
            )
            self.structure_low = 0.0
            self.structure_armed = 0
            self.structure_break_streak = 0
            self._structure_bars.clear()
            self._entry_datetime = trade.datetime
            self.entry_gate_mode = self._pending_entry_mode
            self.exit_reason = ""

        elif (
            trade.offset == Offset.CLOSE
            and self.pos == 0
        ):
            if not self.exit_reason:
                self.exit_reason = "atr_or_emergency_stop"

            self._reset_position_state()

        self.put_event()

    def on_stop_order(
        self,
        stop_order: StopOrder,
    ) -> None:
        pass
