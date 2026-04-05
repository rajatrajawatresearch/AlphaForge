"""Feature engineering for ML price prediction."""

import logging

import numpy as np
import pandas as pd

from ..indicators.engine import IndicatorEngine

logger = logging.getLogger("alphaforge.ai")


class FeatureEngine:
    """Builds feature matrices from OHLCV data for ML models."""

    def __init__(self, indicator_engine: IndicatorEngine | None = None):
        self.indicators = indicator_engine or IndicatorEngine()

    def build_features(self, df: pd.DataFrame, horizon_days: int = 5) -> tuple[pd.DataFrame, pd.Series]:
        """Build feature matrix and target variable.

        Args:
            df: OHLCV DataFrame with columns: timestamp, open, high, low, close, volume
            horizon_days: Forward return horizon for target.

        Returns:
            (X, y) where X is feature matrix, y is target (1=up, 0=down).
        """
        if len(df) < 60:
            raise ValueError(f"Need at least 60 rows, got {len(df)}")

        df = df.copy().reset_index(drop=True)

        # Compute all indicators
        df = self.indicators.compute_all(df)

        # ── Price features ──
        df["return_1d"] = df["close"].pct_change(1)
        df["return_5d"] = df["close"].pct_change(5)
        df["return_10d"] = df["close"].pct_change(10)
        df["return_20d"] = df["close"].pct_change(20)
        df["log_return_1d"] = np.log(df["close"] / df["close"].shift(1))

        # Price ratios
        df["close_to_open"] = df["close"] / df["open"] - 1
        df["high_to_low"] = df["high"] / df["low"] - 1
        df["close_to_high"] = df["close"] / df["high"]
        df["close_to_low"] = df["close"] / df["low"]

        # ── Volume features ──
        df["volume_ratio_20"] = df["volume"] / df["volume"].rolling(20).mean()
        df["volume_change"] = df["volume"].pct_change(1)

        # ── Rolling statistics (60-day window) ──
        df["rolling_mean_60"] = df["close"].rolling(60).mean()
        df["rolling_std_60"] = df["close"].rolling(60).std()
        df["rolling_skew_60"] = df["return_1d"].rolling(60).apply(lambda x: x.skew(), raw=False)
        df["rolling_kurt_60"] = df["return_1d"].rolling(60).apply(lambda x: x.kurt(), raw=False)
        df["price_vs_mean_60"] = df["close"] / df["rolling_mean_60"] - 1

        # ── Temporal features ──
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"])
            df["day_of_week"] = ts.dt.dayofweek
            df["month"] = ts.dt.month
            df["day_of_month"] = ts.dt.day

        # ── Target variable ──
        # Forward N-day return: 1 if positive, 0 if negative
        df["forward_return"] = df["close"].shift(-horizon_days) / df["close"] - 1
        df["target"] = (df["forward_return"] > 0).astype(int)

        # Select feature columns
        feature_cols = self._get_feature_columns(df)
        available = [c for c in feature_cols if c in df.columns]

        # Drop rows with NaN
        subset = df[available + ["target"]].dropna()

        X = subset[available]
        y = subset["target"]

        logger.info("Features built: %d samples, %d features", len(X), len(available))
        return X, y

    def build_live_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build features for live prediction (no target, returns latest row)."""
        if len(df) < 60:
            return pd.DataFrame()

        df = df.copy().reset_index(drop=True)
        df = self.indicators.compute_all(df)

        df["return_1d"] = df["close"].pct_change(1)
        df["return_5d"] = df["close"].pct_change(5)
        df["return_10d"] = df["close"].pct_change(10)
        df["return_20d"] = df["close"].pct_change(20)
        df["log_return_1d"] = np.log(df["close"] / df["close"].shift(1))
        df["close_to_open"] = df["close"] / df["open"] - 1
        df["high_to_low"] = df["high"] / df["low"] - 1
        df["close_to_high"] = df["close"] / df["high"]
        df["close_to_low"] = df["close"] / df["low"]
        df["volume_ratio_20"] = df["volume"] / df["volume"].rolling(20).mean()
        df["volume_change"] = df["volume"].pct_change(1)
        df["rolling_mean_60"] = df["close"].rolling(60).mean()
        df["rolling_std_60"] = df["close"].rolling(60).std()
        df["price_vs_mean_60"] = df["close"] / df["rolling_mean_60"] - 1

        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"])
            df["day_of_week"] = ts.dt.dayofweek
            df["month"] = ts.dt.month

        feature_cols = self._get_feature_columns(df)
        available = [c for c in feature_cols if c in df.columns]
        return df[available].tail(1).dropna(axis=1)

    def _get_feature_columns(self, df: pd.DataFrame) -> list[str]:
        """Get list of feature column names."""
        exclude = {"timestamp", "target", "forward_return", "rolling_mean_60",
                    "rolling_std_60", "open", "high", "low", "close", "volume"}
        # Include all numeric columns that aren't in exclude set
        return [c for c in df.select_dtypes(include=[np.number]).columns if c not in exclude]
