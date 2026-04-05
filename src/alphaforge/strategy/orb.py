"""Opening Range Breakout (ORB) strategy.

Waits for the first 15-minute candle (09:15–09:30), then trades breakouts
above the high or below the low of that opening range.
"""

import logging
from datetime import time

import pandas as pd

from ..config.schema import ORBConfig
from ..indicators.engine import IndicatorEngine
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class ORBStrategy(BaseStrategy):
    """Opening Range Breakout — intraday breakout strategy."""

    def __init__(self, config: ORBConfig, indicator_engine: IndicatorEngine):
        super().__init__(name="orb", enabled=config.enabled)
        self.config = config
        self.indicators = indicator_engine
        # State
        self._range_high: dict[str, float] = {}
        self._range_low: dict[str, float] = {}
        self._range_set: dict[str, bool] = {}
        self._traded_today: dict[str, bool] = {}

    async def on_start(self) -> None:
        self._range_high.clear()
        self._range_low.clear()
        self._range_set.clear()
        self._traded_today.clear()
        logger.info("ORB: Reset for new session")

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        candle_time = ts.time()

        # Phase 1: Build opening range from 09:15 candle
        if time(9, 15) <= candle_time < time(9, 30) and not self._range_set.get(symbol):
            # First 15-min candle
            self._range_high[symbol] = candle.high
            self._range_low[symbol] = candle.low
            self._range_set[symbol] = True
            logger.info("ORB: Range set for %s — HIGH: %.2f LOW: %.2f",
                        symbol, candle.high, candle.low)
            return None

        # Phase 2: Look for breakouts after 09:30
        if not self._range_set.get(symbol):
            return None

        if self._traded_today.get(symbol):
            return None

        # Don't trade after 15:00 (need time for exit)
        if candle_time >= time(15, 0):
            return None

        range_high = self._range_high[symbol]
        range_low = self._range_low[symbol]
        buffer = range_high * (self.config.breakout_buffer_pct / 100.0)

        # Compute indicators for ATR-based stop-loss
        if len(history) >= 14:
            history = self.indicators.compute_subset(history, ["atr"])
            atr = history["atr_14"].dropna().iloc[-1] if "atr_14" in history.columns else None
        else:
            atr = None

        # Bullish breakout
        if candle.close > range_high + buffer:
            sl = range_low
            risk = candle.close - sl
            target = candle.close + risk * 2  # 1:2 R:R

            self._traded_today[symbol] = True
            parts = symbol.split(":")
            exchange = parts[0] if len(parts) > 1 else "NSE"
            sym = parts[1] if len(parts) > 1 else symbol

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.BUY,
                confidence=0.75,
                suggested_price=candle.close,
                stop_loss=sl,
                target=target,
                product=self.config.product,
                metadata={"range_high": range_high, "range_low": range_low, "atr": atr},
            )

        # Bearish breakdown
        if candle.close < range_low - buffer:
            sl = range_high
            risk = sl - candle.close
            target = candle.close - risk * 2

            self._traded_today[symbol] = True
            parts = symbol.split(":")
            exchange = parts[0] if len(parts) > 1 else "NSE"
            sym = parts[1] if len(parts) > 1 else symbol

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.SELL,
                confidence=0.75,
                suggested_price=candle.close,
                stop_loss=sl,
                target=target,
                product=self.config.product,
                metadata={"range_high": range_high, "range_low": range_low, "atr": atr},
            )

        return None

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{s}" for s in self.config.symbols]

    @property
    def required_intervals(self) -> list[str]:
        return [self.config.candle_interval]
