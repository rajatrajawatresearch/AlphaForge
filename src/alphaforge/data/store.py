"""Historical data store using Parquet files."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..broker.client import KiteClient
from ..utils.time import IST

logger = logging.getLogger("alphaforge.data")

DATA_DIR = Path("data/historical")


class DataStore:
    """Parquet-based historical OHLCV data storage and retrieval."""

    def __init__(self, client: KiteClient | None = None):
        self.client = client
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _path(self, exchange: str, symbol: str, interval: str) -> Path:
        p = DATA_DIR / exchange / symbol
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{interval}.parquet"

    def save_candles(self, exchange: str, symbol: str, interval: str, df: pd.DataFrame) -> None:
        """Save candle data to Parquet. Appends to existing data, deduplicates by timestamp."""
        path = self._path(exchange, symbol, interval)

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df]).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        df.to_parquet(path, index=False)
        logger.debug("Saved %d candles: %s:%s [%s]", len(df), exchange, symbol, interval)

    def load_candles(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> pd.DataFrame:
        """Load candle data from Parquet store."""
        path = self._path(exchange, symbol, interval)

        if not path.exists():
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.read_parquet(path)

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if from_date:
                df = df[df["timestamp"] >= pd.Timestamp(from_date)]
            if to_date:
                df = df[df["timestamp"] <= pd.Timestamp(to_date)]

        return df.sort_values("timestamp").reset_index(drop=True)

    def has_data(self, exchange: str, symbol: str, interval: str) -> bool:
        """Check if any data exists for this instrument/interval."""
        return self._path(exchange, symbol, interval).exists()

    def get_latest_date(self, exchange: str, symbol: str, interval: str) -> datetime | None:
        """Get the most recent data point's timestamp."""
        df = self.load_candles(exchange, symbol, interval)
        if df.empty:
            return None
        return df["timestamp"].max().to_pydatetime()

    async def download_and_store(
        self,
        instrument_token: int,
        exchange: str,
        symbol: str,
        interval: str,
        days: int = 365,
    ) -> pd.DataFrame:
        """Download historical data from Kite and store in Parquet."""
        if not self.client:
            raise ValueError("KiteClient required for downloading data")

        to_date = datetime.now(IST)
        from_date = to_date - timedelta(days=days)

        # Check existing data — only download missing range
        latest = self.get_latest_date(exchange, symbol, interval)
        if latest:
            from_date = max(from_date, latest + timedelta(minutes=1))
            if from_date >= to_date:
                logger.info("Data up to date for %s:%s [%s]", exchange, symbol, interval)
                return self.load_candles(exchange, symbol, interval)

        logger.info("Downloading %s:%s [%s] from %s to %s",
                     exchange, symbol, interval,
                     from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"))

        # Kite API limits historical data range per request
        # For minute data: max 60 days per request
        # For day data: max 2000 days
        max_days = 60 if "minute" in interval else 2000
        all_data = []
        chunk_start = from_date

        while chunk_start < to_date:
            chunk_end = min(chunk_start + timedelta(days=max_days), to_date)
            try:
                data = await self.client.get_historical_data(
                    instrument_token=instrument_token,
                    from_date=chunk_start.strftime("%Y-%m-%d %H:%M:%S"),
                    to_date=chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                    interval=interval,
                )
                all_data.extend(data)
                logger.debug("  Chunk: %d candles (%s to %s)",
                             len(data), chunk_start.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d"))
            except Exception as e:
                logger.error("Download error for %s:%s chunk %s: %s",
                             exchange, symbol, chunk_start.strftime("%Y-%m-%d"), e)
            chunk_start = chunk_end + timedelta(days=1)

        if not all_data:
            logger.warning("No data downloaded for %s:%s", exchange, symbol)
            return self.load_candles(exchange, symbol, interval)

        # Convert to DataFrame
        df = pd.DataFrame(all_data)
        if "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})

        self.save_candles(exchange, symbol, interval, df)
        full_df = self.load_candles(exchange, symbol, interval)
        logger.info("Stored %d candles for %s:%s [%s]", len(full_df), exchange, symbol, interval)
        return full_df
