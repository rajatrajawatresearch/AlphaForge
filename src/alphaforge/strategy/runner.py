"""Async strategy runner — executes all strategies in parallel."""

import asyncio
import logging

import pandas as pd

from ..types import Candle, Signal
from ..utils.errors import StrategyError
from .base import BaseStrategy
from .registry import StrategyRegistry

logger = logging.getLogger("alphaforge.strategy")


class StrategyRunner:
    """Runs all enabled strategies concurrently via asyncio.TaskGroup."""

    def __init__(
        self,
        registry: StrategyRegistry,
        signal_queue: asyncio.Queue,
        shutdown_event: asyncio.Event,
    ):
        self.registry = registry
        self.signal_queue = signal_queue
        self.shutdown_event = shutdown_event
        # Per-strategy candle queues
        self._candle_queues: dict[str, asyncio.Queue] = {}
        # History buffers per symbol
        self._history: dict[str, pd.DataFrame] = {}

    def get_candle_queue(self, strategy_name: str) -> asyncio.Queue:
        """Get or create candle queue for a strategy."""
        if strategy_name not in self._candle_queues:
            self._candle_queues[strategy_name] = asyncio.Queue(maxsize=1000)
        return self._candle_queues[strategy_name]

    def update_history(self, symbol: str, candle: Candle, max_rows: int = 500) -> pd.DataFrame:
        """Append candle to symbol history and return updated DataFrame."""
        row = {
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }
        if symbol not in self._history:
            self._history[symbol] = pd.DataFrame(columns=row.keys())

        self._history[symbol] = pd.concat(
            [self._history[symbol], pd.DataFrame([row])],
            ignore_index=True,
        ).tail(max_rows)

        return self._history[symbol]

    def set_history(self, symbol: str, df: pd.DataFrame) -> None:
        """Pre-load history for a symbol (e.g., from data store)."""
        self._history[symbol] = df

    async def run(self) -> None:
        """Run all enabled strategies in parallel."""
        strategies = self.registry.get_all_enabled()
        if not strategies:
            logger.warning("No strategies enabled")
            return

        logger.info("Starting %d strategies", len(strategies))

        # Call on_start for all strategies
        for strategy in strategies:
            try:
                await strategy.on_start()
            except Exception as e:
                logger.error("Strategy %s on_start failed: %s", strategy.name, e)

        # Run strategy loops
        tasks = []
        for strategy in strategies:
            task = asyncio.create_task(
                self._run_strategy(strategy),
                name=f"strategy-{strategy.name}",
            )
            tasks.append(task)

        # Wait for shutdown
        await self.shutdown_event.wait()

        # Cancel all strategy tasks
        for task in tasks:
            task.cancel()

        # Call on_stop for all strategies
        for strategy in strategies:
            try:
                await strategy.on_stop()
            except Exception as e:
                logger.error("Strategy %s on_stop failed: %s", strategy.name, e)

        logger.info("All strategies stopped")

    async def _run_strategy(self, strategy: BaseStrategy) -> None:
        """Run a single strategy's candle processing loop."""
        queue = self.get_candle_queue(strategy.name)
        logger.info("Strategy loop started: %s", strategy.name)

        while not self.shutdown_event.is_set():
            try:
                candle = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if not strategy.enabled:
                continue

            symbol = f"{candle.exchange}:{candle.tradingsymbol}"
            history = self.update_history(symbol, candle)

            try:
                signal = await strategy.on_candle(symbol, candle, history)
                strategy.record_success()

                if signal:
                    await self.signal_queue.put(signal)
                    logger.info("Signal from %s: %s %s %s @ %.2f",
                                strategy.name, signal.signal_type,
                                signal.exchange, signal.tradingsymbol,
                                signal.suggested_price)

            except Exception as e:
                logger.error("Strategy %s error: %s", strategy.name, e)
                should_disable = strategy.record_error()
                if should_disable:
                    logger.error("Strategy %s auto-disabled after %d consecutive errors",
                                 strategy.name, strategy._max_errors)
                    strategy.enabled = False

    async def dispatch_candle(self, candle: Candle) -> None:
        """Send a candle to all relevant strategy queues."""
        for strategy in self.registry.get_all_enabled():
            if candle.interval in strategy.required_intervals:
                symbol_key = f"{candle.exchange}:{candle.tradingsymbol}"
                if symbol_key in strategy.required_symbols:
                    queue = self.get_candle_queue(strategy.name)
                    try:
                        queue.put_nowait(candle)
                    except asyncio.QueueFull:
                        logger.warning("Queue full for strategy %s", strategy.name)
