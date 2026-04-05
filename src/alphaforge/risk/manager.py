"""Central risk management engine — pre-trade gate for all signals."""

import logging

from ..config.schema import RiskSection
from ..constants import Exchange, OrderType, Product, TransactionType, Variety
from ..types import OrderRequest, RiskRejection, Signal, SignalType
from .kill_switch import KillSwitch
from .limits import StrategyLimits
from .position_sizer import PositionSizer

logger = logging.getLogger("alphaforge.risk")


class RiskManager:
    """Pre-trade risk gate. Every signal must pass through here before becoming an order."""

    def __init__(
        self,
        config: RiskSection,
        kill_switch: KillSwitch,
    ):
        self.config = config
        self.kill_switch = kill_switch
        self.position_sizer = PositionSizer(
            total_capital=config.initial_capital,
            max_risk_per_trade_pct=config.max_capital_per_trade_pct,
            atr_multiplier=config.trailing_stop_atr_multiplier,
        )
        self.limits = StrategyLimits(
            total_capital=config.initial_capital,
            strategy_limits=config.strategy_limits,
        )
        self._total_positions = 0

    def evaluate_signal(
        self,
        signal: Signal,
        current_atr: float | None = None,
        lot_size: int = 1,
    ) -> OrderRequest | RiskRejection:
        """Evaluate a trading signal against all risk rules.

        Returns OrderRequest if approved, RiskRejection if denied.
        """
        # 1. Kill switch check
        if self.kill_switch.is_triggered:
            return RiskRejection(signal=signal, reason="Kill switch is active")

        # 2. Only process BUY/SELL signals
        if signal.signal_type == SignalType.HOLD:
            return RiskRejection(signal=signal, reason="HOLD signal — no action")

        # 3. Check concurrent position limit
        if self._total_positions >= self.config.max_concurrent_positions:
            return RiskRejection(
                signal=signal,
                reason=f"Max concurrent positions reached ({self._total_positions}/{self.config.max_concurrent_positions})",
            )

        # 4. Check strategy allocation limits
        can_open, reason = self.limits.can_open_position(signal.strategy_name)
        if not can_open:
            return RiskRejection(signal=signal, reason=reason)

        # 5. Compute position size
        quantity = signal.quantity
        if quantity == 0 and current_atr and current_atr > 0:
            quantity = self.position_sizer.compute(
                price=signal.suggested_price,
                atr=current_atr,
                lot_size=lot_size,
            )

        if quantity <= 0:
            return RiskRejection(signal=signal, reason="Computed quantity is zero (insufficient capital or ATR)")

        # 6. Validate stop-loss
        if signal.stop_loss <= 0:
            return RiskRejection(signal=signal, reason="No stop-loss set")

        if signal.signal_type == SignalType.BUY and signal.stop_loss >= signal.suggested_price:
            return RiskRejection(signal=signal, reason="Stop-loss above entry for BUY signal")

        if signal.signal_type == SignalType.SELL and signal.stop_loss <= signal.suggested_price:
            return RiskRejection(signal=signal, reason="Stop-loss below entry for SELL signal")

        # 7. Build order request
        txn_type = TransactionType.BUY if signal.signal_type == SignalType.BUY else TransactionType.SELL

        order = OrderRequest(
            tradingsymbol=signal.tradingsymbol,
            exchange=Exchange(signal.exchange),
            transaction_type=txn_type,
            quantity=quantity,
            order_type=OrderType.LIMIT,
            product=Product(signal.product),
            variety=Variety.REGULAR,
            price=signal.suggested_price,
            tag=signal.strategy_name[:20],
            strategy_name=signal.strategy_name,
            signal=signal,
        )

        # Register position in limits tracker
        capital_used = quantity * signal.suggested_price
        self.limits.register_position(signal.strategy_name, capital_used)
        self._total_positions += 1

        logger.info(
            "APPROVED: %s %s %s x%d @ %.2f | SL: %.2f | Target: %.2f | Strategy: %s",
            txn_type, signal.exchange, signal.tradingsymbol,
            quantity, signal.suggested_price, signal.stop_loss, signal.target,
            signal.strategy_name,
        )

        return order

    def release_position(self, strategy_name: str, capital_used: float) -> None:
        """Called when a position is closed."""
        self.limits.release_position(strategy_name, capital_used)
        self._total_positions = max(0, self._total_positions - 1)

    def get_risk_state(self) -> dict:
        """Get current risk state for dashboard."""
        return {
            "total_positions": self._total_positions,
            "max_positions": self.config.max_concurrent_positions,
            "kill_switch_active": self.kill_switch.is_triggered,
            "strategy_limits": self.limits.get_state(),
        }
