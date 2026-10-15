"""引擎内统一的数据结构。所有时间均为北京时间（不带时区的 datetime）。

证券代码统一为 "513530.SH" / "159920.SZ" 形式，由各网关负责转换。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Quote:
    symbol: str
    time: datetime                  # 行情时间（交易所/数据源时间）
    last: float
    bid: float                      # 买一
    ask: float                      # 卖一
    iopv: float | None = None       # 基金份额参考净值；拿不到时为 None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def valid(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid

    @property
    def premium(self) -> float | None:
        """溢价（%）= 中间价 / IOPV − 1；IOPV 无效时为 None。"""
        if not self.valid or not self.iopv or self.iopv <= 0:
            return None
        return (self.mid / self.iopv - 1) * 100


@dataclass
class Snapshot:
    """决策时点的一组行情。stale 中的标的数据缺失或过期，策略不应据此交易。"""
    time: datetime
    quotes: dict[str, Quote]
    stale: set[str] = field(default_factory=set)


@dataclass
class TargetIntent:
    """策略的交易意图：在本策略预算内，各标的目标权重（合计 ≤ 1，未列出的标的目标为 0）。"""
    strategy: str
    intent_id: str
    created: datetime
    targets: dict[str, float]
    ttl_seconds: float = 120.0
    max_slip_ticks: int = 1
    reason: str = ""


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"            # 本地已创建，尚未确认报出
    SUBMITTED = "SUBMITTED"        # 已报
    PARTIAL = "PARTIAL"            # 部分成交
    CANCELLING = "CANCELLING"      # 撤单已发出
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"        # 已撤（可能部分成交后撤）
    REJECTED = "REJECTED"

    @property
    def active(self) -> bool:
        return self in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL, OrderStatus.CANCELLING)


@dataclass
class Order:
    client_id: str
    strategy: str
    intent_id: str
    symbol: str
    side: Side
    price: float
    volume: int
    created: datetime
    status: OrderStatus = OrderStatus.PENDING
    filled: int = 0
    avg_price: float = 0.0
    broker_id: str | None = None
    updated: datetime | None = None
    reason: str = ""

    @property
    def remaining(self) -> int:
        return self.volume - self.filled

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"], d["status"] = self.side.value, self.status.value
        return d


@dataclass(frozen=True)
class OrderUpdate:
    client_id: str
    status: OrderStatus
    filled: int                     # 累计成交数量
    avg_price: float
    time: datetime
    broker_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Trade:
    trade_id: str
    client_id: str
    symbol: str
    side: Side
    price: float
    volume: int
    time: datetime
    fee: float = 0.0


@dataclass(frozen=True)
class CorporateAction:
    """除权除息：现金分红（每份）或份额拆分/合并（比例 > 1 为拆分）。"""
    date: datetime
    symbol: str
    cash_per_share: float = 0.0
    split_ratio: float = 1.0


@dataclass(frozen=True)
class GatewayStatus:
    """网关连接状态变化。connected=False 时引擎暂停交易，直到人工处理后重启。"""
    time: datetime
    connected: bool
    message: str = ""
