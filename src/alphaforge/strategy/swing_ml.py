"""Swing ML strategy.

Uses XGBoost + LightGBM ensemble to predict multi-day price moves.
Runs post-market and pre-market for position entry/exit.
"""

import logging
from datetime import time

import pandas as pd

from ..ai.ensemble import EnsembleScorer
from ..ai.feature_engine import FeatureEngine
from ..ai.ml_predictor import MLPredictor
from ..config.schema import SwingMLConfig
from ..indicators.engine import IndicatorEngine
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class SwingMLStrategy(BaseStrategy):
    """Swing ML — multi-day trades based on ML price prediction."""

    def __init__(
        self,
        config: SwingMLConfig,
        ml_predictor: MLPredictor,
        feature_engine: FeatureEngine,
        ensemble_scorer: EnsembleScorer | None = None,
    ):
        super().__init__(name="swing_ml", enabled=config.enabled)
        self.config = config
        self.predictor = ml_predictor
        self.features = feature_engine
        self.scorer = ensemble_scorer or EnsembleScorer()
        self._predictions: dict[str, float] = {}
        self._traded_today: set[str] = set()

    async def on_start(self) -> None:
        self._traded_today.clear()
        logger.info("Swing ML: Watching %d symbols, horizon=%d days",
                     len(self.config.symbols), self.config.prediction_horizon_days)

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)

        # Only analyze at end of day (15:15-15:30) or start of day (09:15-09:30)
        is_eod = time(15, 15) <= ts.time() <= time(15, 30)
        is_sod = time(9, 15) <= ts.time() <= time(9, 30)

        if not (is_eod or is_sod):
            return None

        if symbol in self._traded_today:
            return None

        # Need sufficient history for features
        if len(history) < 60:
            return None

        # Build features
        try:
            X = self.features.build_live_features(history)
            if X.empty:
                return None
        except Exception as e:
            logger.error("Feature building error for %s: %s", symbol, e)
            return None

        # Get ML prediction
        try:
            prob_up, confidence = self.predictor.predict(X)
        except Exception as e:
            logger.error("ML prediction error for %s: %s", symbol, e)
            return None

        # Check confidence threshold
        if confidence < self.config.confidence_threshold:
            return None

        parts = symbol.split(":")
        exchange = parts[0] if len(parts) > 1 else "NSE"
        sym = parts[1] if len(parts) > 1 else symbol

        # Determine signal
        if prob_up > 0.5 + self.config.confidence_threshold / 2:
            signal_type = SignalType.BUY
            price = candle.close
            sl = round(price * 0.97, 2)  # 3% stop-loss for swing
            target = round(price * 1.06, 2)  # 6% target (1:2 R:R)

            self._traded_today.add(symbol)

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=signal_type,
                confidence=confidence,
                suggested_price=price,
                stop_loss=sl,
                target=target,
                product=self.config.product,
                metadata={
                    "ml_probability": round(prob_up, 4),
                    "ml_confidence": round(confidence, 4),
                    "horizon_days": self.config.prediction_horizon_days,
                },
            )

        elif prob_up < 0.5 - self.config.confidence_threshold / 2:
            signal_type = SignalType.SELL
            price = candle.close
            sl = round(price * 1.03, 2)
            target = round(price * 0.94, 2)

            self._traded_today.add(symbol)

            return Signal(
                strategy_name=self.name,
                tradingsymbol=sym,
                exchange=exchange,
                signal_type=signal_type,
                confidence=confidence,
                suggested_price=price,
                stop_loss=sl,
                target=target,
                product=self.config.product,
                metadata={
                    "ml_probability": round(prob_up, 4),
                    "ml_confidence": round(confidence, 4),
                    "horizon_days": self.config.prediction_horizon_days,
                },
            )

        return None

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{s}" for s in self.config.symbols]

    @property
    def required_intervals(self) -> list[str]:
        return ["day"]
