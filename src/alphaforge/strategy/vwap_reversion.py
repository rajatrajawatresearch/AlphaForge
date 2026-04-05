"""VWAP Mean Reversion strategy.

Trades reversion to VWAP when price deviates beyond N standard deviations.
"""

import logging
from datetime import time

import numpy as np
import pandas as pd

from ..config.schema import VWAPReversionConfig
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class VWAPReversionStrategy(BaseStrategy):
    """VWAP Mean Reversion — intraday mean-reversion strategy."""

    def __init__(self, config: VWAPReversionConfig):
        super().__init__(name="vwap_reversion", enabled=config.enabled)
        self.config = config
        # Running VWAP state per symbol
        self._cum_volume: dict[str, float] = {}
        self._cum_tp_volume: dict[str, float] = {}
        self._traded_today: dict[str, int] = {}

    async def on_start(self) -> None:
        self._cum_volume.clear()
        self._cum_tp_volume.clear()
        self._traded_today.clear()
        logger.info("VWAP Reversion: Reset for new session")

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)

        # Only trade during market hours, not in final 30 min
        if ts.time() < time(9, 30) or ts.time() >= time(15, 0):
            return None

        # Update running VWAP
        typical_price = (candle.high + candle.low + candle.close) / 3.0
        vol = max(candle.volume, 1)

        self._cum_tp_volume[symbol] = self._cum_tp_volume.get(symbol, 0) + typical_price * vol
        self._cum_volume[symbol] = self._cum_volume.get(symbol, 0) + vol

        vwap = self._cum_tp_volume[symbol] / self._cum_volume[symbol]

        # Need enough history for standard deviation
        if len(history) < 20:
            return None

        # Compute deviation from VWAP
        closes = history["close"].tail(20)
        std = closes.std()
        if std == 0 or np.isnan(std):
            return None

        deviation = (candle.close - vwap) / std
        threshold = self.config.deviation_threshold

        parts = symbol.split(":")
        exchange = parts[0] if len(parts) > 1 else "NSE"
        sym = parts[1] if len(parts) > 1 else symbol

        # Buy when price is significantly below VWAP
        if deviation < -threshold:
            reversion_target = candle.close + (vwap - candle.close) * (self.config.reversion_target_pct / 100.0)
            sl = candle.close - std * (threshold + 0.5)

            self._traded_today[symbol] = self._traded_today.get(symbol, 0) + 1

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.BUY,
                confidence=min(abs(deviation) / 3.0, 1.0),
                suggested_price=candle.close,
                stop_loss=round(sl, 2),
                target=round(reversion_target, 2),
                product=self.config.product,
                metadata={"vwap": round(vwap, 2), "deviation": round(deviation, 2), "std": round(std, 2)},
            )

        # Sell when price is significantly above VWAP
        if deviation > threshold:
            reversion_target = candle.close - (candle.close - vwap) * (self.config.reversion_target_pct / 100.0)
            sl = candle.close + std * (threshold + 0.5)

            self._traded_today[symbol] = self._traded_today.get(symbol, 0) + 1

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.SELL,
                confidence=min(abs(deviation) / 3.0, 1.0),
                suggested_price=candle.close,
                stop_loss=round(sl, 2),
                target=round(reversion_target, 2),
                product=self.config.product,
                metadata={"vwap": round(vwap, 2), "deviation": round(deviation, 2), "std": round(std, 2)},
            )

        return None

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{s}" for s in self.config.symbols]

    @property
    def required_intervals(self) -> list[str]:
        return ["5minute"]
