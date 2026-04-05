"""Shared data types used across the system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .constants import Exchange, OrderType, Product, TransactionType, Validity, Variety


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_token: int
    tradingsymbol: str
    exchange: str
    last_price: float
    last_quantity: int
    volume: int
    buy_quantity: int
    sell_quantity: int
    ohlc: dict[str, float]
    change: float
    timestamp: datetime
    depth: dict[str, list[dict]] | None = None
    oi: int = 0


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    tradingsymbol: str = ""
    exchange: str = ""
    interval: str = ""


@dataclass(frozen=True, slots=True)
class Signal:
    strategy_name: str
    tradingsymbol: str
    exchange: str
    signal_type: SignalType
    confidence: float
    suggested_price: float
    stop_loss: float
    target: float
    quantity: int = 0  # 0 = let risk manager compute
    product: str = "MIS"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True, slots=True)
class OrderRequest:
    tradingsymbol: str
    exchange: Exchange
    transaction_type: TransactionType
    quantity: int
    order_type: OrderType
    product: Product
    variety: Variety = Variety.REGULAR
    price: float | None = None
    trigger_price: float | None = None
    validity: Validity = Validity.DAY
    tag: str = ""
    strategy_name: str = ""
    signal: Signal | None = None


@dataclass(slots=True)
class OrderResponse:
    order_id: str
    status: OrderStatus
    tradingsymbol: str
    exchange: str
    transaction_type: str
    quantity: int
    price: float
    average_price: float = 0.0
    filled_quantity: int = 0
    pending_quantity: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    strategy_name: str = ""
    tag: str = ""


@dataclass(slots=True)
class Position:
    tradingsymbol: str
    exchange: str
    product: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    strategy_name: str = ""
    entry_time: datetime | None = None
    stop_loss: float | None = None
    target: float | None = None


@dataclass(frozen=True, slots=True)
class RiskRejection:
    signal: Signal
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
