"""Load historical data for backtesting."""

import logging
from datetime import datetime

import pandas as pd

from ..data.store import DataStore

logger = logging.getLogger("alphaforge.backtest")


class BacktestDataLoader:
    """Loads historical data from the data store for backtesting."""

    def __init__(self, store: DataStore):
        self.store = store

    def load(
        self,
        symbols: list[str],
        interval: str = "15minute",
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load historical data for multiple symbols.

        Args:
            symbols: List of "EXCHANGE:SYMBOL" strings.
            interval: Candle interval.
            start_date: Start date filter.
            end_date: End date filter.

        Returns:
            Dict of symbol → DataFrame.
        """
        data = {}
        for symbol in symbols:
            parts = symbol.split(":")
            exchange = parts[0] if len(parts) > 1 else "NSE"
            sym = parts[-1]

            from_dt = None
            to_dt = None
            if start_date:
                from_dt = pd.Timestamp(start_date).to_pydatetime()
            if end_date:
                to_dt = pd.Timestamp(end_date).to_pydatetime()

            df = self.store.load_candles(exchange, sym, interval, from_dt, to_dt)
            if df.empty:
                logger.warning("No data for %s [%s]", symbol, interval)
                continue

            data[symbol] = df
            logger.info("Loaded %d candles for %s [%s]", len(df), symbol, interval)

        return data
