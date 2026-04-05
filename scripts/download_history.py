#!/usr/bin/env python3
"""Download historical data for specified instruments."""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alphaforge.broker.auth import authenticate
from alphaforge.broker.client import KiteClient
from alphaforge.broker.rate_limiter import RateLimiter
from alphaforge.config import load_config
from alphaforge.data.instruments import InstrumentManager
from alphaforge.data.store import DataStore
from alphaforge.utils.logging import setup_logging


async def download(args):
    config = load_config()
    logger = setup_logging(level="INFO")

    kite = authenticate(config.broker.api_key, config.broker.api_secret)
    client = KiteClient(kite, RateLimiter())
    instruments = InstrumentManager(client)
    store = DataStore(client)

    await instruments.load([args.exchange])

    token = instruments.get_token(args.exchange, args.symbol)
    if not token:
        print(f"Instrument not found: {args.exchange}:{args.symbol}")
        sys.exit(1)

    print(f"Downloading {args.exchange}:{args.symbol} (token: {token})")
    print(f"  Interval: {args.interval}")
    print(f"  Days: {args.days}")

    df = await store.download_and_store(
        instrument_token=token,
        exchange=args.exchange,
        symbol=args.symbol,
        interval=args.interval,
        days=args.days,
    )
    print(f"\nDone. {len(df)} candles stored.")
    if not df.empty:
        print(f"  From: {df['timestamp'].min()}")
        print(f"  To:   {df['timestamp'].max()}")


def main():
    parser = argparse.ArgumentParser(description="Download historical data")
    parser.add_argument("--symbol", required=True, help="Trading symbol (e.g., RELIANCE)")
    parser.add_argument("--exchange", default="NSE", help="Exchange (NSE, BSE, NFO)")
    parser.add_argument("--interval", default="15minute", help="Candle interval")
    parser.add_argument("--days", type=int, default=365, help="Number of days to download")
    args = parser.parse_args()
    asyncio.run(download(args))


if __name__ == "__main__":
    main()
