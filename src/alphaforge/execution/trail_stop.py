"""Trailing stop-loss manager."""

import logging

from ..broker.client import KiteClient
from ..types import Position

logger = logging.getLogger("alphaforge.orders")


class TrailingStopManager:
    """Manages trailing stop-losses for open positions."""

    def __init__(self, client: KiteClient, atr_multiplier: float = 2.0):
        self.client = client
        self.atr_multiplier = atr_multiplier
        # Track best prices since entry: "NSE:RELIANCE:strategy" → best price
        self._best_prices: dict[str, float] = {}
        # Current SL order IDs
        self._sl_orders: dict[str, str] = {}

    def update(self, position: Position, current_price: float, current_atr: float) -> float | None:
        """Update trailing stop for a position. Returns new SL price if changed."""
        key = f"{position.exchange}:{position.tradingsymbol}:{position.strategy_name}"

        if position.quantity > 0:  # Long
            best = max(self._best_prices.get(key, current_price), current_price)
            self._best_prices[key] = best
            new_sl = round(best - current_atr * self.atr_multiplier, 2)
            old_sl = position.stop_loss or 0

            if new_sl > old_sl:
                logger.debug("Trailing SL updated %s: %.2f → %.2f (best: %.2f)",
                             key, old_sl, new_sl, best)
                return new_sl

        elif position.quantity < 0:  # Short
            best = min(self._best_prices.get(key, current_price), current_price)
            self._best_prices[key] = best
            new_sl = round(best + current_atr * self.atr_multiplier, 2)
            old_sl = position.stop_loss or float("inf")

            if new_sl < old_sl:
                logger.debug("Trailing SL updated %s: %.2f → %.2f (best: %.2f)",
                             key, old_sl, new_sl, best)
                return new_sl

        return None

    def remove(self, position: Position) -> None:
        """Remove tracking for a closed position."""
        key = f"{position.exchange}:{position.tradingsymbol}:{position.strategy_name}"
        self._best_prices.pop(key, None)
        self._sl_orders.pop(key, None)
