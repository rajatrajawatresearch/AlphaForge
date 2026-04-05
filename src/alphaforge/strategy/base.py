"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod

import pandas as pd

from ..types import Candle, Signal, Tick


class BaseStrategy(ABC):
    """All strategies must implement this interface."""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        self._consecutive_errors = 0
        self._max_errors = 10  # Auto-disable after this many consecutive failures

    @abstractmethod
    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        """Called when a new candle completes.

        Args:
            symbol: Trading symbol.
            candle: The completed candle.
            history: Historical DataFrame with OHLCV + indicators.

        Returns:
            Signal if trade opportunity detected, None otherwise.
        """
        ...

    async def on_tick(self, tick: Tick) -> Signal | None:
        """Called on every tick (override for tick-sensitive strategies)."""
        return None

    async def on_start(self) -> None:
        """Called at market open. Override for initialization."""
        pass

    async def on_stop(self) -> None:
        """Called at market close. Override for cleanup."""
        pass

    @property
    @abstractmethod
    def required_symbols(self) -> list[str]:
        """List of symbols this strategy needs (e.g., ["NSE:RELIANCE"])."""
        ...

    @property
    @abstractmethod
    def required_intervals(self) -> list[str]:
        """List of candle intervals needed (e.g., ["minute", "15minute"])."""
        ...

    def record_error(self) -> bool:
        """Record a strategy error. Returns True if strategy should be disabled."""
        self._consecutive_errors += 1
        return self._consecutive_errors >= self._max_errors

    def record_success(self) -> None:
        """Reset error counter on successful execution."""
        self._consecutive_errors = 0
