"""ATR-based position sizing with capital limits."""

import logging
import math

logger = logging.getLogger("alphaforge.risk")


class PositionSizer:
    """Computes position size based on ATR and capital risk limits."""

    def __init__(
        self,
        total_capital: float,
        max_risk_per_trade_pct: float = 2.0,
        atr_multiplier: float = 2.0,
    ):
        self.total_capital = total_capital
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.atr_multiplier = atr_multiplier

    def compute(
        self,
        price: float,
        atr: float,
        lot_size: int = 1,
        max_quantity: int | None = None,
    ) -> int:
        """Compute position size.

        Args:
            price: Current price of the instrument.
            atr: Current ATR value.
            lot_size: Minimum lot size (1 for equity, varies for F&O).
            max_quantity: Hard cap on quantity.

        Returns:
            Quantity to trade (always a multiple of lot_size).
        """
        if price <= 0 or atr <= 0:
            return 0

        # Risk amount = capital * risk percentage
        risk_amount = self.total_capital * (self.max_risk_per_trade_pct / 100.0)

        # Risk per share = ATR * multiplier (this is the stop-loss distance)
        risk_per_share = atr * self.atr_multiplier

        # Raw quantity = risk_amount / risk_per_share
        raw_qty = risk_amount / risk_per_share

        # Also cap by maximum capital per trade
        max_by_capital = risk_amount / price * 10  # allow up to 10x risk as position
        raw_qty = min(raw_qty, max_by_capital)

        # Round down to lot size
        qty = int(raw_qty // lot_size) * lot_size

        # Apply hard cap
        if max_quantity:
            qty = min(qty, max_quantity)

        # Ensure at least one lot
        if qty < lot_size:
            # Check if even one lot fits within risk
            if lot_size * risk_per_share <= risk_amount * 1.5:  # 50% tolerance for min lot
                qty = lot_size
            else:
                qty = 0  # Can't afford even one lot within risk limits

        return qty

    def compute_stop_loss(self, entry_price: float, atr: float, is_long: bool = True) -> float:
        """Compute stop-loss price based on ATR."""
        distance = atr * self.atr_multiplier
        if is_long:
            return round(entry_price - distance, 2)
        return round(entry_price + distance, 2)

    def compute_target(self, entry_price: float, stop_loss: float, rr_ratio: float = 2.0) -> float:
        """Compute target price based on risk-reward ratio."""
        risk = abs(entry_price - stop_loss)
        reward = risk * rr_ratio
        if entry_price > stop_loss:  # Long
            return round(entry_price + reward, 2)
        return round(entry_price - reward, 2)

    def update_capital(self, new_capital: float) -> None:
        """Update total capital (e.g., after P&L changes)."""
        self.total_capital = new_capital
