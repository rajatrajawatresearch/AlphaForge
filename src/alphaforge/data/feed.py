"""Real-time data feed manager — distributes ticks to subscribers."""

import asyncio
import logging

from ..broker.ticker import AsyncTicker
from ..types import Candle, Tick
from .candle_builder import CandleBuilder

logger = logging.getLogger("alphaforge.data")


class DataFeed:
    """Manages the real-time data pipeline: ticks → candles → subscribers."""

    def __init__(self, ticker: AsyncTicker, intervals: list[str] | None = None):
        self.ticker = ticker
        self.candle_builder = CandleBuilder(intervals or ["minute", "5minute", "15minute"])

        # Subscribers
        self._tick_queues: list[asyncio.Queue] = []
        self._candle_queues: dict[str, list[asyncio.Queue]] = {}  # interval → list of queues
        self._running = False

    def subscribe_ticks(self, queue: asyncio.Queue) -> None:
        """Subscribe a queue to receive all raw ticks."""
        self._tick_queues.append(queue)

    def subscribe_candles(self, interval: str, queue: asyncio.Queue) -> None:
        """Subscribe a queue to receive completed candles of a given interval."""
        if interval not in self._candle_queues:
            self._candle_queues[interval] = []
        self._candle_queues[interval].append(queue)

    def _distribute_candle(self, candle: Candle) -> None:
        """Called by CandleBuilder when a candle completes."""
        queues = self._candle_queues.get(candle.interval, [])
        for q in queues:
            try:
                q.put_nowait(candle)
            except asyncio.QueueFull:
                logger.warning("Candle queue full for %s, dropping candle", candle.interval)

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Main loop: read ticks from WebSocket, build candles, distribute."""
        self._running = True
        self.candle_builder.on_candle(self._distribute_candle)
        logger.info("DataFeed started")

        tick_count = 0
        candle_count = 0

        while not shutdown_event.is_set():
            try:
                # Wait for tick with timeout so we can check shutdown
                tick = await asyncio.wait_for(self.ticker.get_tick(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            tick_count += 1
            if tick_count % 1000 == 0:
                logger.debug("Processed %d ticks, %d candles", tick_count, candle_count)

            # Distribute raw ticks
            for q in self._tick_queues:
                try:
                    q.put_nowait(tick)
                except asyncio.QueueFull:
                    pass  # Drop if subscriber is slow

            # Build candles
            completed = self.candle_builder.process_tick(tick)
            candle_count += len(completed)

        # Flush remaining candles
        self.candle_builder.flush_all()
        self._running = False
        logger.info("DataFeed stopped. Total: %d ticks, %d candles", tick_count, candle_count)
