"""Build OHLCV candles from streaming ticks."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from ..types import Candle, Tick
from ..utils.time import IST

logger = logging.getLogger("alphaforge.data")

# Interval durations in seconds
INTERVAL_SECONDS = {
    "minute": 60,
    "3minute": 180,
    "5minute": 300,
    "10minute": 600,
    "15minute": 900,
    "30minute": 1800,
    "60minute": 3600,
}


def _align_timestamp(dt: datetime, interval_seconds: int) -> datetime:
    """Align a timestamp to the start of its candle interval."""
    # Seconds since midnight
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds = (dt - midnight).total_seconds()
    aligned = int(seconds // interval_seconds) * interval_seconds
    return midnight + timedelta(seconds=aligned)


class CandleBuilder:
    """Aggregates ticks into OHLCV candles for multiple intervals."""

    def __init__(self, intervals: list[str] | None = None):
        """Initialize candle builder.

        Args:
            intervals: List of intervals to build (e.g., ["minute", "5minute", "15minute"]).
        """
        self.intervals = intervals or ["minute", "5minute", "15minute"]
        # {(token, interval): {"open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}}
        self._building: dict[tuple[int, str], dict] = defaultdict(dict)
        # {(token, interval): aligned_start_time}
        self._current_period: dict[tuple[int, str], datetime] = {}
        # Completed candle callbacks
        self._callbacks: list[callable] = []

    def on_candle(self, callback: callable) -> None:
        """Register a callback for completed candles. Signature: callback(candle: Candle)"""
        self._callbacks.append(callback)

    def _emit(self, candle: Candle) -> None:
        for cb in self._callbacks:
            try:
                cb(candle)
            except Exception as e:
                logger.error("Candle callback error: %s", e)

    def process_tick(self, tick: Tick) -> list[Candle]:
        """Process a tick and return any completed candles."""
        completed = []

        for interval in self.intervals:
            interval_sec = INTERVAL_SECONDS[interval]
            key = (tick.instrument_token, interval)

            ts = tick.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)

            aligned = _align_timestamp(ts, interval_sec)

            current = self._current_period.get(key)

            if current is None:
                # First tick for this instrument/interval
                self._current_period[key] = aligned
                self._building[key] = {
                    "open": tick.last_price,
                    "high": tick.last_price,
                    "low": tick.last_price,
                    "close": tick.last_price,
                    "volume": tick.volume,
                    "symbol": tick.tradingsymbol,
                    "exchange": tick.exchange,
                }
            elif aligned > current:
                # New period — emit completed candle
                b = self._building[key]
                candle = Candle(
                    timestamp=current,
                    open=b["open"],
                    high=b["high"],
                    low=b["low"],
                    close=b["close"],
                    volume=b["volume"],
                    tradingsymbol=b["symbol"],
                    exchange=b["exchange"],
                    interval=interval,
                )
                completed.append(candle)
                self._emit(candle)

                # Start new period
                self._current_period[key] = aligned
                self._building[key] = {
                    "open": tick.last_price,
                    "high": tick.last_price,
                    "low": tick.last_price,
                    "close": tick.last_price,
                    "volume": tick.volume,
                    "symbol": tick.tradingsymbol,
                    "exchange": tick.exchange,
                }
            else:
                # Same period — update OHLCV
                b = self._building[key]
                b["high"] = max(b["high"], tick.last_price)
                b["low"] = min(b["low"], tick.last_price)
                b["close"] = tick.last_price
                b["volume"] = tick.volume  # Kite volume is cumulative

        return completed

    def flush_all(self) -> list[Candle]:
        """Flush all in-progress candles (e.g., at market close)."""
        completed = []
        for key, b in self._building.items():
            period = self._current_period.get(key)
            if period and b:
                _, interval = key
                candle = Candle(
                    timestamp=period,
                    open=b["open"],
                    high=b["high"],
                    low=b["low"],
                    close=b["close"],
                    volume=b["volume"],
                    tradingsymbol=b["symbol"],
                    exchange=b["exchange"],
                    interval=interval,
                )
                completed.append(candle)
                self._emit(candle)
        self._building.clear()
        self._current_period.clear()
        return completed
