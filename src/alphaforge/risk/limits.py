"""Per-strategy allocation limits and concurrent position tracking."""

import logging
from collections import defaultdict

from ..config.schema import StrategyLimit

logger = logging.getLogger("alphaforge.risk")


class StrategyLimits:
    """Tracks and enforces per-strategy allocation and position limits."""

    def __init__(self, total_capital: float, strategy_limits: dict[str, StrategyLimit]):
        self.total_capital = total_capital
        self.limits = strategy_limits
        # Current state
        self._positions: dict[str, int] = defaultdict(int)  # strategy → open position count
        self._allocated: dict[str, float] = defaultdict(float)  # strategy → capital allocated

    def can_open_position(self, strategy_name: str) -> tuple[bool, str]:
        """Check if a strategy can open a new position."""
        limit = self.limits.get(strategy_name)
        if not limit:
            return True, ""

        # Check position count
        current_positions = self._positions[strategy_name]
        if current_positions >= limit.max_positions:
            return False, f"Strategy '{strategy_name}' at max positions ({current_positions}/{limit.max_positions})"

        # Check allocation
        max_allocation = self.total_capital * (limit.max_allocation_pct / 100.0)
        if self._allocated[strategy_name] >= max_allocation:
            return False, (f"Strategy '{strategy_name}' at max allocation "
                           f"(₹{self._allocated[strategy_name]:,.0f}/₹{max_allocation:,.0f})")

        return True, ""

    def remaining_allocation(self, strategy_name: str) -> float:
        """Get remaining capital allocation for a strategy."""
        limit = self.limits.get(strategy_name)
        if not limit:
            return self.total_capital
        max_alloc = self.total_capital * (limit.max_allocation_pct / 100.0)
        return max(0, max_alloc - self._allocated[strategy_name])

    def register_position(self, strategy_name: str, capital_used: float) -> None:
        """Record that a position was opened."""
        self._positions[strategy_name] += 1
        self._allocated[strategy_name] += capital_used
        logger.info("Position opened: %s (count: %d, allocated: ₹%.0f)",
                     strategy_name, self._positions[strategy_name], self._allocated[strategy_name])

    def release_position(self, strategy_name: str, capital_used: float) -> None:
        """Record that a position was closed."""
        self._positions[strategy_name] = max(0, self._positions[strategy_name] - 1)
        self._allocated[strategy_name] = max(0, self._allocated[strategy_name] - capital_used)

    def get_state(self) -> dict:
        """Get current allocation state."""
        state = {}
        for name, limit in self.limits.items():
            max_alloc = self.total_capital * (limit.max_allocation_pct / 100.0)
            state[name] = {
                "positions": self._positions[name],
                "max_positions": limit.max_positions,
                "allocated": self._allocated[name],
                "max_allocation": max_alloc,
            }
        return state

    def reset(self) -> None:
        """Reset all tracking (e.g., start of new trading day)."""
        self._positions.clear()
        self._allocated.clear()
