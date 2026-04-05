"""Order status tracking and position management."""

import logging
from collections.abc import Callable
from datetime import datetime

from ..types import OrderResponse, OrderStatus, Position
from ..utils.time import IST

logger = logging.getLogger("alphaforge.orders")


class PositionTracker:
    """Tracks open positions from filled orders."""

    def __init__(self):
        self._positions: dict[str, Position] = {}  # "NSE:RELIANCE:strategy" → Position
        self._realized_pnl: float = 0.0
        self._trade_log: list[dict] = []
        self._on_pnl_callbacks: list[Callable[[float], None]] = []

    def on_realized_pnl(self, callback: Callable[[float], None]) -> None:
        """Register a callback fired when a position closes. Receives the P&L delta."""
        self._on_pnl_callbacks.append(callback)

    def process_fill(self, order: OrderResponse, last_price: float | None = None) -> None:
        """Process a filled order — open or close position."""
        key = f"{order.exchange}:{order.tradingsymbol}:{order.strategy_name}"
        lp = last_price or order.average_price

        if key in self._positions:
            pos = self._positions[key]
            if order.transaction_type == "BUY" and pos.quantity < 0:
                # Covering short
                pnl = (pos.average_price - order.average_price) * order.filled_quantity
                self._close_position(key, pnl, order)
            elif order.transaction_type == "SELL" and pos.quantity > 0:
                # Selling long
                pnl = (order.average_price - pos.average_price) * order.filled_quantity
                self._close_position(key, pnl, order)
            else:
                # Adding to position
                self._add_to_position(key, order)
        else:
            # New position
            qty = order.filled_quantity if order.transaction_type == "BUY" else -order.filled_quantity
            self._positions[key] = Position(
                tradingsymbol=order.tradingsymbol,
                exchange=order.exchange,
                product=order.tag,
                quantity=qty,
                average_price=order.average_price,
                last_price=lp,
                pnl=0.0,
                strategy_name=order.strategy_name,
                entry_time=order.timestamp,
            )

    def _close_position(self, key: str, pnl: float, order: OrderResponse) -> None:
        pos = self._positions.pop(key, None)
        self._realized_pnl += pnl
        for cb in self._on_pnl_callbacks:
            try:
                cb(pnl)
            except Exception as e:
                logger.error("P&L callback error: %s", e)
        self._trade_log.append({
            "symbol": order.tradingsymbol,
            "exchange": order.exchange,
            "strategy": order.strategy_name,
            "pnl": pnl,
            "close_time": datetime.now(IST),
            "entry_price": pos.average_price if pos else 0,
            "exit_price": order.average_price,
        })
        logger.info("Position closed: %s P&L: ₹%.2f", key, pnl)

    def _add_to_position(self, key: str, order: OrderResponse) -> None:
        pos = self._positions[key]
        old_value = pos.quantity * pos.average_price
        new_qty = order.filled_quantity if order.transaction_type == "BUY" else -order.filled_quantity
        new_value = new_qty * order.average_price
        total_qty = pos.quantity + new_qty
        if total_qty != 0:
            avg = (old_value + new_value) / total_qty
        else:
            avg = pos.average_price
        self._positions[key] = Position(
            tradingsymbol=pos.tradingsymbol,
            exchange=pos.exchange,
            product=pos.product,
            quantity=total_qty,
            average_price=abs(avg),
            last_price=pos.last_price,
            pnl=pos.pnl,
            strategy_name=pos.strategy_name,
            entry_time=pos.entry_time,
        )

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update last prices and unrealized P&L. prices: {"NSE:RELIANCE": 2850.0}"""
        for key, pos in self._positions.items():
            price_key = f"{pos.exchange}:{pos.tradingsymbol}"
            if price_key in prices:
                lp = prices[price_key]
                pnl = (lp - pos.average_price) * pos.quantity
                self._positions[key] = Position(
                    tradingsymbol=pos.tradingsymbol,
                    exchange=pos.exchange,
                    product=pos.product,
                    quantity=pos.quantity,
                    average_price=pos.average_price,
                    last_price=lp,
                    pnl=pnl,
                    strategy_name=pos.strategy_name,
                    entry_time=pos.entry_time,
                    stop_loss=pos.stop_loss,
                    target=pos.target,
                )

    @property
    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.pnl for p in self._positions.values())

    @property
    def total_pnl(self) -> float:
        return self._realized_pnl + self.unrealized_pnl

    @property
    def trade_log(self) -> list[dict]:
        return list(self._trade_log)
