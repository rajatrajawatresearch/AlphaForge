"""Strategy registration and lifecycle management."""

import logging

from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class StrategyRegistry:
    """Manages strategy instances and their lifecycle."""

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        if strategy.name in self._strategies:
            raise ValueError(f"Strategy '{strategy.name}' already registered")
        self._strategies[strategy.name] = strategy
        logger.info("Registered strategy: %s (enabled: %s)", strategy.name, strategy.enabled)

    def get(self, name: str) -> BaseStrategy | None:
        return self._strategies.get(name)

    def get_all(self) -> list[BaseStrategy]:
        return list(self._strategies.values())

    def get_all_enabled(self) -> list[BaseStrategy]:
        return [s for s in self._strategies.values() if s.enabled]

    def get_required_instruments(self) -> set[str]:
        """Union of all symbols required by enabled strategies."""
        instruments = set()
        for s in self.get_all_enabled():
            instruments.update(s.required_symbols)
        return instruments

    def disable(self, name: str) -> None:
        s = self._strategies.get(name)
        if s:
            s.enabled = False
            logger.warning("Strategy disabled: %s", name)

    def enable(self, name: str) -> None:
        s = self._strategies.get(name)
        if s:
            s.enabled = True
            logger.info("Strategy enabled: %s", name)
