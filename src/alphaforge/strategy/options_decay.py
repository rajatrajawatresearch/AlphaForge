"""Options Premium Decay strategy.

Sells OTM options on weekly expiry to capture theta decay.
"""

import logging
from datetime import datetime, time

import pandas as pd

from ..config.schema import OptionsDecayConfig
from ..data.instruments import InstrumentManager
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class OptionsDecayStrategy(BaseStrategy):
    """Options Premium Decay — sell OTM options for theta income."""

    def __init__(self, config: OptionsDecayConfig, instrument_manager: InstrumentManager | None = None):
        super().__init__(name="options_decay", enabled=config.enabled)
        self.config = config
        self.instruments = instrument_manager
        self._positions_today: dict[str, int] = {}
        self._last_check: datetime | None = None

    async def on_start(self) -> None:
        self._positions_today.clear()
        self._last_check = None
        logger.info("Options Decay: Reset for new session")

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)

        # Only check at specific times — not every candle
        # Entry window: 09:30–10:30 (capture morning premium)
        if ts.time() < time(9, 30) or ts.time() > time(10, 30):
            return None

        # Check cooldown (once per 15 min)
        if self._last_check and (ts - self._last_check).total_seconds() < 900:
            return None
        self._last_check = ts

        # Need instrument manager for option chain
        if not self.instruments:
            return None

        underlying_symbol = symbol.split(":")[-1]
        if underlying_symbol not in self.config.underlyings:
            return None

        # Find weekly expiry options
        options = self.instruments.get_option_chain(underlying_symbol)
        if not options:
            return None

        # Filter by DTE
        today = ts.date()
        valid_options = []
        for opt in options:
            expiry = opt.get("expiry")
            if not expiry:
                continue
            if isinstance(expiry, str):
                try:
                    expiry = datetime.strptime(expiry, "%Y-%m-%d").date()
                except ValueError:
                    continue
            dte = (expiry - today).days
            if 0 < dte <= self.config.days_to_expiry_max:
                valid_options.append({**opt, "dte": dte})

        if not valid_options:
            return None

        # Find OTM options N strikes away from current price
        spot = candle.close
        otm_calls = [o for o in valid_options
                      if o.get("instrument_type") == "CE"
                      and float(o.get("strike", 0)) > spot]
        otm_puts = [o for o in valid_options
                     if o.get("instrument_type") == "PE"
                     and float(o.get("strike", 0)) < spot]

        # Sort by strike distance
        otm_calls.sort(key=lambda x: float(x.get("strike", 0)))
        otm_puts.sort(key=lambda x: float(x.get("strike", 0)), reverse=True)

        # Select N-th OTM strike
        n = self.config.otm_strikes_away
        target_option = None
        if len(otm_calls) > n:
            target_option = otm_calls[n]
        elif len(otm_puts) > n:
            target_option = otm_puts[n]

        if not target_option:
            return None

        strike = float(target_option.get("strike", 0))
        opt_symbol = target_option.get("tradingsymbol", "")
        opt_type = target_option.get("instrument_type", "")

        # Check if already positioned
        if opt_symbol in self._positions_today:
            return None

        self._positions_today[opt_symbol] = 1

        # SELL the option (premium collection)
        # Stop-loss at 2x premium (set by risk manager)
        sl_multiplier = 2.0

        return Signal(
            strategy_name=self.name,
            tradingsymbol=opt_symbol,
            exchange="NFO",
            signal_type=SignalType.SELL,
            confidence=0.7,
            suggested_price=strike,  # approximate; real price from quote
            stop_loss=round(strike * sl_multiplier, 2),
            target=0.0,  # Target is premium going to zero at expiry
            product=self.config.product,
            metadata={
                "underlying": underlying_symbol,
                "strike": strike,
                "option_type": opt_type,
                "dte": target_option.get("dte"),
                "spot_price": spot,
            },
        )

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{u}" for u in self.config.underlyings]

    @property
    def required_intervals(self) -> list[str]:
        return ["15minute"]
