"""Instrument master download, cache, and lookup."""

import csv
import logging
from datetime import datetime
from pathlib import Path

from ..broker.client import KiteClient
from ..utils.time import IST

logger = logging.getLogger("alphaforge.data")

CACHE_DIR = Path("data/instruments")


class InstrumentManager:
    """Downloads, caches, and provides lookups for NSE/BSE/NFO instruments."""

    def __init__(self, client: KiteClient):
        self.client = client
        self._instruments: list[dict] = []
        self._by_token: dict[int, dict] = {}
        self._by_symbol: dict[str, dict] = {}  # "NSE:RELIANCE" → instrument

    async def load(self, exchanges: list[str] | None = None) -> None:
        """Load instrument master — from cache if today's, else download."""
        exchanges = exchanges or ["NSE", "BSE", "NFO"]
        today = datetime.now(IST).strftime("%Y-%m-%d")
        cache_file = CACHE_DIR / f"instruments_{today}.csv"

        if cache_file.exists():
            logger.info("Loading instruments from cache: %s", cache_file)
            self._load_from_csv(cache_file)
        else:
            logger.info("Downloading instrument master for %s", ", ".join(exchanges))
            all_instruments = []
            for exchange in exchanges:
                instruments = await self.client.get_instruments(exchange)
                all_instruments.extend(instruments)
                logger.info("  %s: %d instruments", exchange, len(instruments))

            self._instruments = all_instruments
            self._build_indexes()
            self._save_to_csv(cache_file)
            logger.info("Instrument master cached: %d total", len(self._instruments))

    def _build_indexes(self) -> None:
        self._by_token = {}
        self._by_symbol = {}
        for inst in self._instruments:
            token = inst.get("instrument_token")
            exchange = inst.get("exchange", "")
            symbol = inst.get("tradingsymbol", "")
            if token:
                self._by_token[token] = inst
            if exchange and symbol:
                self._by_symbol[f"{exchange}:{symbol}"] = inst

    def _save_to_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self._instruments:
            return
        fieldnames = list(self._instruments[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self._instruments)

    def _load_from_csv(self, path: Path) -> None:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            self._instruments = []
            for row in reader:
                # Convert numeric fields
                for field in ("instrument_token", "exchange_token", "lot_size", "tick_size"):
                    if field in row and row[field]:
                        try:
                            row[field] = int(float(row[field]))
                        except (ValueError, TypeError):
                            pass
                for field in ("last_price", "strike"):
                    if field in row and row[field]:
                        try:
                            row[field] = float(row[field])
                        except (ValueError, TypeError):
                            pass
                self._instruments.append(row)
        self._build_indexes()
        logger.info("Loaded %d instruments from cache", len(self._instruments))

    def get_token(self, exchange: str, tradingsymbol: str) -> int | None:
        """Look up instrument_token for an exchange:symbol pair."""
        inst = self._by_symbol.get(f"{exchange}:{tradingsymbol}")
        if inst:
            return inst.get("instrument_token")
        return None

    def get_symbol(self, instrument_token: int) -> tuple[str, str] | None:
        """Look up (tradingsymbol, exchange) for an instrument_token."""
        inst = self._by_token.get(instrument_token)
        if inst:
            return (inst.get("tradingsymbol", ""), inst.get("exchange", ""))
        return None

    def get_instrument(self, exchange: str, tradingsymbol: str) -> dict | None:
        """Get full instrument details."""
        return self._by_symbol.get(f"{exchange}:{tradingsymbol}")

    def get_lot_size(self, exchange: str, tradingsymbol: str) -> int:
        """Get lot size for F&O instruments (1 for equity)."""
        inst = self.get_instrument(exchange, tradingsymbol)
        if inst:
            return int(inst.get("lot_size", 1))
        return 1

    def get_option_chain(self, underlying: str, expiry: str | None = None) -> list[dict]:
        """Get option chain for an underlying (NFO instruments)."""
        results = []
        for inst in self._instruments:
            if (inst.get("exchange") == "NFO"
                    and inst.get("name") == underlying
                    and inst.get("instrument_type") in ("CE", "PE")):
                if expiry is None or str(inst.get("expiry", "")) == expiry:
                    results.append(inst)
        return sorted(results, key=lambda x: (x.get("expiry", ""), float(x.get("strike", 0))))

    def search(self, query: str, exchange: str | None = None) -> list[dict]:
        """Search instruments by tradingsymbol substring."""
        query = query.upper()
        results = []
        for inst in self._instruments:
            if exchange and inst.get("exchange") != exchange:
                continue
            if query in inst.get("tradingsymbol", ""):
                results.append(inst)
        return results[:50]

    @property
    def token_to_symbol_map(self) -> dict[int, tuple[str, str]]:
        """Return mapping of instrument_token → (tradingsymbol, exchange)."""
        return {
            token: (inst.get("tradingsymbol", ""), inst.get("exchange", ""))
            for token, inst in self._by_token.items()
        }
