"""时钟与交易时段。实盘用系统时间（服务器为北京时间），回测由回放推进。"""
from __future__ import annotations

from datetime import datetime, time

# 连续竞价时段；14:57–15:00 为收盘集合竞价，不在此发起换仓
SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(14, 57)))
MORNING_FIRST = 9 * 60 + 31      # 决策时点按“分钟结束”计：上午第一根为 09:31
AFTERNOON_FIRST = 13 * 60 + 1


class RealClock:
    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)


class SimClock:
    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2000, 1, 1)

    def now(self) -> datetime:
        return self._now

    def set(self, t: datetime) -> None:
        if t < self._now:
            raise ValueError(f"回放时钟不能倒退：{t} < {self._now}")
        self._now = t


def in_session(t: datetime) -> bool:
    return any(a <= t.time() < b for a, b in SESSIONS)


def decision_slot(t: datetime, step_minutes: int) -> tuple | None:
    """t 所在的决策时点编号；不在决策窗口（09:31–11:30、13:01–14:56）内返回 None。

    以分钟结束时刻对齐：上午 09:31、09:36…，下午 13:01、13:06…，与研究中按分钟快照每 step 取一个一致。
    """
    m = t.hour * 60 + t.minute
    if MORNING_FIRST <= m <= 11 * 60 + 30:
        k = (m - MORNING_FIRST) // step_minutes
    elif AFTERNOON_FIRST <= m <= 14 * 60 + 56:
        k = 1000 + (m - AFTERNOON_FIRST) // step_minutes
    else:
        return None
    return (t.date(), k)


class DecisionScheduler:
    """每个决策时点只触发一次：时点内第一次看到行情时触发。"""

    def __init__(self, step_minutes: int):
        self.step = step_minutes
        self._last: tuple | None = None

    def due(self, t: datetime) -> bool:
        slot = decision_slot(t, self.step)
        if slot is None or slot == self._last:
            return False
        self._last = slot
        return True
