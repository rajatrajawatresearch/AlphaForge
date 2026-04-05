"""Momentum Scalper strategy.

Uses RSI extremes on 1-minute candles with volume confirmation
for quick scalping trades.
"""

import logging
from datetime import datetime, time, timedelta

import pandas as pd

from ..config.schema import MomentumScalperConfig
from ..indicators.engine import IndicatorEngine
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class MomentumScalperStrategy(BaseStrategy):
    """Momentum Scalper — quick in-and-out on RSI extremes + volume spikes."""

    def __init__(self, config: MomentumScalperConfig, indicator_engine: IndicatorEngine):
        super().__init__(name="momentum_scalper", enabled=config.enabled)
        self.config = config
        self.indicators = indicator_engine
        self._last_signal_time: dict[str, datetime] = {}
        self._cooldown = timedelta(minutes=15)

    async def on_start(self) -> None:
        self._last_signal_time.clear()
        logger.info("Momentum Scalper: Reset for new session")

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)

        # Only trade 09:20–15:00
        if ts.time() < time(9, 20) or ts.time() >= time(15, 0):
            return None

        # Cooldown check
        last = self._last_signal_time.get(symbol)
        if last and (ts - last) < self._cooldown:
            return None

        # Need enough bars for RSI
        min_bars = max(self.config.rsi_period + 5, 15)
        if len(history) < min_bars:
            return None

        # Compute RSI
        history = self.indicators.compute_subset(history, ["rsi"])
        rsi_col = "rsi_14"  # pandas-ta default
        if rsi_col not in history.columns:
            return None

        rsi = history[rsi_col].iloc[-1]
        if pd.isna(rsi):
            return None

        # Volume spike check: current volume > 1.5x average of last 20 bars
        if len(history) >= 20:
            avg_vol = history["volume"].tail(20).mean()
            vol_spike = candle.volume > avg_vol * 1.5
        else:
            vol_spike = False

        parts = symbol.split(":")
        exchange = parts[0] if len(parts) > 1 else "NSE"
        sym = parts[1] if len(parts) > 1 else symbol

        # Oversold + volume spike → BUY
        if rsi < self.config.rsi_oversold and vol_spike:
            target_pct = 0.004  # 0.4% target
            sl_pct = 0.002      # 0.2% stop-loss

            self._last_signal_time[symbol] = ts

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.BUY,
                confidence=min((self.config.rsi_oversold - rsi) / 25.0, 1.0),
                suggested_price=candle.close,
                stop_loss=round(candle.close * (1 - sl_pct), 2),
                target=round(candle.close * (1 + target_pct), 2),
                product=self.config.product,
                metadata={"rsi": round(rsi, 2), "volume_spike": vol_spike},
            )

        # Overbought + volume spike → SELL
        if rsi > self.config.rsi_overbought and vol_spike:
            target_pct = 0.004
            sl_pct = 0.002

            self._last_signal_time[symbol] = ts

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=SignalType.SELL,
                confidence=min((rsi - self.config.rsi_overbought) / 25.0, 1.0),
                suggested_price=candle.close,
                stop_loss=round(candle.close * (1 + sl_pct), 2),
                target=round(candle.close * (1 - target_pct), 2),
                product=self.config.product,
                metadata={"rsi": round(rsi, 2), "volume_spike": vol_spike},
            )

        return None

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{s}" for s in self.config.symbols]

    @property
    def required_intervals(self) -> list[str]:
        return [self.config.candle_interval]
