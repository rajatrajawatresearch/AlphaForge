#!/usr/bin/env python3
"""Train ML models for swing trading strategy."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alphaforge.ai.feature_engine import FeatureEngine
from alphaforge.ai.ml_predictor import MLPredictor
from alphaforge.broker.auth import authenticate
from alphaforge.broker.client import KiteClient
from alphaforge.broker.rate_limiter import RateLimiter
from alphaforge.config import load_config
from alphaforge.data.instruments import InstrumentManager
from alphaforge.data.store import DataStore
from alphaforge.indicators.engine import IndicatorEngine
from alphaforge.utils.logging import setup_logging


async def train(args):
    config = load_config()
    setup_logging(level="INFO")

    kite = authenticate(config.broker.api_key, config.broker.api_secret)
    client = KiteClient(kite, RateLimiter())
    instruments = InstrumentManager(client)
    store = DataStore(client)

    await instruments.load(["NSE"])

    feature_engine = FeatureEngine(IndicatorEngine())
    predictor = MLPredictor()

    for symbol in args.symbols:
        print(f"\n{'='*50}")
        print(f"Training model for {symbol}")
        print(f"{'='*50}")

        token = instruments.get_token("NSE", symbol)
        if not token:
            print(f"  Symbol not found: {symbol}")
            continue

        # Download/load historical data
        df = await store.download_and_store(
            instrument_token=token,
            exchange="NSE",
            symbol=symbol,
            interval="day",
            days=args.days,
        )

        if len(df) < 100:
            print(f"  Insufficient data: {len(df)} rows (need 100+)")
            continue

        print(f"  Data: {len(df)} daily candles")

        # Build features and train
        try:
            X, y = feature_engine.build_features(df, horizon_days=args.horizon)
            print(f"  Features: {X.shape[1]} | Samples: {len(X)}")
            print(f"  Target distribution: UP={y.sum()}/{len(y)} ({y.mean()*100:.1f}%)")

            metrics = predictor.train(X, y, symbol=symbol)

            print(f"\n  Results:")
            print(f"    XGBoost CV Accuracy:  {metrics['xgb_cv_accuracy']:.3f}")
            print(f"    LightGBM CV Accuracy: {metrics['lgb_cv_accuracy']:.3f}")
            print(f"    Ensemble Accuracy:    {metrics['ensemble_cv_accuracy']:.3f}")

        except Exception as e:
            print(f"  Training error: {e}")
            import traceback
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Train ML models for swing trading")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to train (e.g., RELIANCE TCS)")
    parser.add_argument("--days", type=int, default=365, help="Historical days for training")
    parser.add_argument("--horizon", type=int, default=5, help="Prediction horizon in days")
    args = parser.parse_args()
    asyncio.run(train(args))


if __name__ == "__main__":
    main()
