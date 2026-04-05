"""Async bridge for KiteTicker WebSocket streaming."""

import asyncio
import logging
import threading
import time
from datetime import datetime

from kiteconnect import KiteTicker

from ..types import Tick
from ..utils.time import IST

logger = logging.getLogger("alphaforge.broker")


class AsyncTicker:
    """Bridges KiteTicker's threaded callbacks into asyncio Queues."""

    def __init__(self, api_key: str, access_token: str, max_queue_size: int = 10000):
        self.api_key = api_key
        self.access_token = access_token
        self._ticker: KiteTicker | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=max_queue_size)
        self._connected = asyncio.Event()
        self._stopped = False
        self._last_tick_time: float = 0
        self._subscribed_tokens: set[int] = set()
        self._instrument_map: dict[int, tuple[str, str]] = {}  # token -> (symbol, exchange)
        self._tick_count: int = 0
        self._drop_count: int = 0
        self._permanently_disconnected: bool = False
        self._health_alert_callback: callable | None = None

    def set_instrument_map(self, mapping: dict[int, tuple[str, str]]) -> None:
        """Set instrument_token -> (tradingsymbol, exchange) mapping."""
        self._instrument_map = mapping

    def set_health_alert_callback(self, callback: callable) -> None:
        """Set callback for health alerts. Signature: callback(message: str)"""
        self._health_alert_callback = callback

    def _on_ticks(self, ws, ticks: list[dict]) -> None:
        """Callback: convert raw ticks and push to async queue."""
        self._last_tick_time = time.monotonic()
        self._tick_count += len(ticks)
        for raw in ticks:
            token = raw.get("instrument_token", 0)
            symbol, exchange = self._instrument_map.get(token, (str(token), "NSE"))

            ohlc = raw.get("ohlc", {})
            tick = Tick(
                instrument_token=token,
                tradingsymbol=symbol,
                exchange=exchange,
                last_price=raw.get("last_price", 0.0),
                last_quantity=raw.get("last_quantity", 0),
                volume=raw.get("volume_traded", raw.get("volume", 0)),
                buy_quantity=raw.get("total_buy_quantity", raw.get("buy_quantity", 0)),
                sell_quantity=raw.get("total_sell_quantity", raw.get("sell_quantity", 0)),
                ohlc={
                    "open": ohlc.get("open", 0.0),
                    "high": ohlc.get("high", 0.0),
                    "low": ohlc.get("low", 0.0),
                    "close": ohlc.get("close", 0.0),
                },
                change=raw.get("change", 0.0),
                timestamp=raw.get("exchange_timestamp") or datetime.now(IST),
                depth=raw.get("depth"),
                oi=raw.get("oi", 0),
            )

            if self._loop and not self._stopped:
                self._loop.call_soon_threadsafe(self._enqueue_tick, tick)

    def _enqueue_tick(self, tick: Tick) -> None:
        """Thread-safe enqueue into asyncio queue."""
        try:
            self._tick_queue.put_nowait(tick)
        except asyncio.QueueFull:
            self._drop_count += 1
            # Drop oldest tick if queue is full (backpressure)
            try:
                self._tick_queue.get_nowait()
                self._tick_queue.put_nowait(tick)
            except asyncio.QueueEmpty:
                pass

    def _on_connect(self, ws, response) -> None:
        logger.info("WebSocket connected")
        if self._subscribed_tokens:
            token_list = list(self._subscribed_tokens)
            ws.subscribe(token_list)
            ws.set_mode(ws.MODE_FULL, token_list)
            logger.info("Subscribed to %d instruments in FULL mode", len(token_list))
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_close(self, ws, code, reason) -> None:
        logger.warning("WebSocket closed: code=%s reason=%s", code, reason)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.clear)

    def _on_error(self, ws, code, reason) -> None:
        logger.error("WebSocket error: code=%s reason=%s", code, reason)

    def _on_reconnect(self, ws, attempts_count) -> None:
        logger.info("WebSocket reconnecting (attempt %d)", attempts_count)

    def _on_noreconnect(self, ws) -> None:
        logger.error("WebSocket reconnection failed permanently")
        self._permanently_disconnected = True
        if self._health_alert_callback:
            self._health_alert_callback("WebSocket permanently disconnected")

    def subscribe(self, tokens: list[int]) -> None:
        """Subscribe to instrument tokens."""
        self._subscribed_tokens.update(tokens)
        if self._ticker and self._connected.is_set():
            self._ticker.subscribe(tokens)
            self._ticker.set_mode(self._ticker.MODE_FULL, tokens)

    def unsubscribe(self, tokens: list[int]) -> None:
        """Unsubscribe from instrument tokens."""
        self._subscribed_tokens -= set(tokens)
        if self._ticker and self._connected.is_set():
            self._ticker.unsubscribe(tokens)

    async def get_tick(self) -> Tick:
        """Get next tick from the queue (blocks until available)."""
        return await self._tick_queue.get()

    async def start(self) -> None:
        """Start the WebSocket ticker in a background thread."""
        self._loop = asyncio.get_running_loop()
        self._stopped = False

        self._ticker = KiteTicker(self.api_key, self.access_token)
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_close = self._on_close
        self._ticker.on_error = self._on_error
        self._ticker.on_reconnect = self._on_reconnect
        self._ticker.on_noreconnect = self._on_noreconnect

        self._thread = threading.Thread(target=self._ticker.connect, daemon=True)
        self._thread.start()
        logger.info("WebSocket ticker thread started")

        # Wait for connection
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.error("WebSocket connection timed out after 30s")

    async def stop(self) -> None:
        """Stop the WebSocket ticker."""
        self._stopped = True
        if self._ticker:
            self._ticker.close()
        self._connected.clear()
        logger.info("WebSocket ticker stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def seconds_since_last_tick(self) -> float:
        if self._last_tick_time == 0:
            return float("inf")
        return time.monotonic() - self._last_tick_time

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def drop_count(self) -> int:
        return self._drop_count

    async def health_monitor(self, shutdown_event: asyncio.Event, stale_threshold_s: float = 30.0) -> None:
        """Periodic health check. Auto-restarts ticker on permanent disconnect or stale data."""
        while not shutdown_event.is_set():
            await asyncio.sleep(5.0)

            if self._permanently_disconnected:
                logger.warning("Ticker permanently disconnected — attempting restart")
                await self._restart()
                continue

            if self.is_connected and self.seconds_since_last_tick > stale_threshold_s:
                msg = f"No ticks for {self.seconds_since_last_tick:.0f}s (threshold: {stale_threshold_s}s)"
                logger.warning(msg)
                if self._health_alert_callback:
                    self._health_alert_callback(msg)
                if self.seconds_since_last_tick > stale_threshold_s * 3:
                    logger.error("Tick silence too long — restarting ticker")
                    await self._restart()

    async def _restart(self) -> None:
        """Stop and restart the WebSocket connection."""
        logger.info("Restarting WebSocket ticker...")
        await self.stop()
        self._permanently_disconnected = False
        await asyncio.sleep(2.0)
        await self.start()
