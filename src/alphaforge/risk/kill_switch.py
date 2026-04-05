"""Kill switch — monitors daily P&L and triggers emergency shutdown."""

import asyncio
import logging

from ..broker.client import KiteClient
from ..utils.errors import KillSwitchTriggered

logger = logging.getLogger("alphaforge.risk")


class KillSwitch:
    """Monitors daily P&L and halts all trading if loss limit is breached."""

    def __init__(
        self,
        client: KiteClient,
        initial_capital: float,
        daily_loss_limit_pct: float = 3.0,
        check_interval: float = 1.0,
    ):
        self.client = client
        self.initial_capital = initial_capital
        self.daily_loss_limit = initial_capital * (daily_loss_limit_pct / 100.0)
        self.check_interval = check_interval
        self._triggered = False
        self._realized_pnl: float = 0.0
        self._manual_trigger = False

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def add_realized_pnl(self, pnl: float) -> None:
        """Add realized P&L from a closed trade."""
        self._realized_pnl += pnl

    def trigger_manual(self) -> None:
        """Manually trigger kill switch (e.g., from dashboard button)."""
        self._manual_trigger = True

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Main loop: check P&L every second, trigger if limit breached."""
        logger.info("Kill switch active — loss limit: ₹%.0f (%.1f%%)",
                     self.daily_loss_limit, self.daily_loss_limit / self.initial_capital * 100)

        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(self.check_interval)

                if self._manual_trigger:
                    logger.critical("KILL SWITCH: Manual trigger activated")
                    await self._execute_shutdown(shutdown_event)
                    return

                # Get unrealized P&L from positions
                unrealized_pnl = await self._get_unrealized_pnl()
                total_pnl = self._realized_pnl + unrealized_pnl

                if total_pnl < -self.daily_loss_limit:
                    logger.critical(
                        "KILL SWITCH: Daily loss limit breached! "
                        "P&L: ₹%.0f (realized: ₹%.0f, unrealized: ₹%.0f) | Limit: -₹%.0f",
                        total_pnl, self._realized_pnl, unrealized_pnl, self.daily_loss_limit,
                    )
                    await self._execute_shutdown(shutdown_event)
                    return

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Kill switch must never crash — log and continue
                logger.error("Kill switch error (continuing): %s", e)

    async def _get_unrealized_pnl(self) -> float:
        """Sum unrealized P&L across all positions."""
        try:
            positions = await self.client.get_positions()
            total = 0.0
            for pos in positions.get("net", []):
                total += pos.get("pnl", 0.0)
            return total
        except Exception as e:
            logger.error("Failed to get positions for P&L check: %s", e)
            return 0.0

    async def _execute_shutdown(self, shutdown_event: asyncio.Event) -> None:
        """Emergency shutdown: cancel orders, square off, stop everything."""
        self._triggered = True

        logger.critical("Executing emergency shutdown...")

        # Step 1: Cancel all pending orders
        try:
            cancelled = await self.client.cancel_all_orders()
            logger.critical("Cancelled %d pending orders", len(cancelled))
        except Exception as e:
            logger.error("Error cancelling orders: %s", e)

        # Step 2: Square off all positions
        try:
            squared = await self.client.square_off_all()
            logger.critical("Squared off %d positions", len(squared))
        except Exception as e:
            logger.error("Error squaring off positions: %s", e)

        # Step 3: Signal all tasks to stop
        shutdown_event.set()
        logger.critical("Shutdown event set — all strategies will stop")

    def reset(self) -> None:
        """Reset for new trading day."""
        self._triggered = False
        self._realized_pnl = 0.0
        self._manual_trigger = False
