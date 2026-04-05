"""Technical indicator computation via pandas-ta."""

import logging

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger("alphaforge.indicators")


class IndicatorEngine:
    """Computes technical indicators on OHLCV DataFrames."""

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all standard indicators on a DataFrame.

        Expects columns: timestamp, open, high, low, close, volume
        Returns DataFrame with indicator columns added.
        """
        if df.empty or len(df) < 2:
            return df

        df = df.copy()

        # RSI
        df["rsi_14"] = ta.rsi(df["close"], length=14)

        # MACD
        macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)

        # Bollinger Bands
        bb = ta.bbands(df["close"], length=20, std=2)
        if bb is not None:
            df = pd.concat([df, bb], axis=1)

        # ATR
        df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

        # EMAs
        for period in (9, 21, 50, 200):
            col = f"ema_{period}"
            if len(df) >= period:
                df[col] = ta.ema(df["close"], length=period)

        # ADX
        adx = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx is not None:
            df = pd.concat([df, adx], axis=1)

        # Stochastic RSI
        stochrsi = ta.stochrsi(df["close"], length=14)
        if stochrsi is not None:
            df = pd.concat([df, stochrsi], axis=1)

        # OBV
        df["obv"] = ta.obv(df["close"], df["volume"])

        # CCI
        df["cci_20"] = ta.cci(df["high"], df["low"], df["close"], length=20)

        # SuperTrend
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
        if st is not None:
            df = pd.concat([df, st], axis=1)

        return df

    def compute_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute VWAP (requires intraday data with DatetimeIndex)."""
        df = df.copy()
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        vwap = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        if vwap is not None:
            df["vwap"] = vwap
        df = df.reset_index()
        return df

    def compute_subset(self, df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
        """Compute only specified indicators.

        Supported: rsi, macd, bbands, atr, ema, adx, stochrsi, obv, cci, supertrend, vwap
        """
        df = df.copy()

        if "rsi" in indicators:
            df["rsi_14"] = ta.rsi(df["close"], length=14)

        if "macd" in indicators:
            macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
            if macd is not None:
                df = pd.concat([df, macd], axis=1)

        if "bbands" in indicators:
            bb = ta.bbands(df["close"], length=20, std=2)
            if bb is not None:
                df = pd.concat([df, bb], axis=1)

        if "atr" in indicators:
            df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

        if "ema" in indicators:
            for period in (9, 21, 50, 200):
                if len(df) >= period:
                    df[f"ema_{period}"] = ta.ema(df["close"], length=period)

        if "adx" in indicators:
            adx = ta.adx(df["high"], df["low"], df["close"], length=14)
            if adx is not None:
                df = pd.concat([df, adx], axis=1)

        if "stochrsi" in indicators:
            stochrsi = ta.stochrsi(df["close"], length=14)
            if stochrsi is not None:
                df = pd.concat([df, stochrsi], axis=1)

        if "obv" in indicators:
            df["obv"] = ta.obv(df["close"], df["volume"])

        if "cci" in indicators:
            df["cci_20"] = ta.cci(df["high"], df["low"], df["close"], length=20)

        if "supertrend" in indicators:
            st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
            if st is not None:
                df = pd.concat([df, st], axis=1)

        if "vwap" in indicators:
            df = self.compute_vwap(df)

        return df
