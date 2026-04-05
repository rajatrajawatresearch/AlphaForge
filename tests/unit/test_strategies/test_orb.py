"""Tests for Opening Range Breakout strategy."""

from datetime import datetime

import pandas as pd
import pytest

from alphaforge.config.schema import ORBConfig
from alphaforge.indicators.engine import IndicatorEngine
from alphaforge.strategy.orb import ORBStrategy
from alphaforge.types import Candle, SignalType
from alphaforge.utils.time import IST


def _make_config() -> ORBConfig:
    return ORBConfig(
        enabled=True,
        symbols=["RELIANCE"],
        candle_interval="15minute",
        breakout_buffer_pct=0.1,
        stop_loss_pct=0.5,
        target_pct=1.0,
        product="MIS",
    )


def _make_candle(h: int, m: int, o: float, hi: float, lo: float, c: float, vol: int = 1000) -> Candle:
    return Candle(
        timestamp=datetime(2026, 4, 6, h, m, 0, tzinfo=IST),
        open=o, high=hi, low=lo, close=c, volume=vol,
        tradingsymbol="RELIANCE", exchange="NSE", interval="15minute",
    )


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


@pytest.mark.asyncio
async def test_orb_sets_range():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    # 09:15 candle sets the opening range
    candle = _make_candle(9, 15, 2800, 2850, 2790, 2830)
    result = await strat.on_candle("NSE:RELIANCE", candle, _empty_history())
    assert result is None  # No signal during range setting
    assert strat._range_high["NSE:RELIANCE"] == 2850
    assert strat._range_low["NSE:RELIANCE"] == 2790


@pytest.mark.asyncio
async def test_orb_bullish_breakout():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    # Set range
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 15, 2800, 2850, 2790, 2830), _empty_history())
    # Breakout above range high
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(9, 45, 2860, 2870, 2855, 2865), _empty_history())
    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.stop_loss == 2790  # Range low


@pytest.mark.asyncio
async def test_orb_bearish_breakdown():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 15, 2800, 2850, 2790, 2830), _empty_history())
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(9, 45, 2780, 2785, 2770, 2775), _empty_history())
    assert signal is not None
    assert signal.signal_type == SignalType.SELL
    assert signal.stop_loss == 2850


@pytest.mark.asyncio
async def test_orb_no_signal_within_range():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 15, 2800, 2850, 2790, 2830), _empty_history())
    # Close within range
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(9, 45, 2820, 2840, 2800, 2825), _empty_history())
    assert signal is None


@pytest.mark.asyncio
async def test_orb_no_second_trade():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 15, 2800, 2850, 2790, 2830), _empty_history())
    # First breakout
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 45, 2860, 2870, 2855, 2865), _empty_history())
    # Second breakout should be ignored
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(10, 0, 2880, 2900, 2875, 2895), _empty_history())
    assert signal is None


@pytest.mark.asyncio
async def test_orb_no_trade_after_1500():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    await strat.on_candle("NSE:RELIANCE", _make_candle(9, 15, 2800, 2850, 2790, 2830), _empty_history())
    # Try breakout at 15:05
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(15, 5, 2860, 2870, 2855, 2865), _empty_history())
    assert signal is None


@pytest.mark.asyncio
async def test_orb_no_signal_before_range_set():
    strat = ORBStrategy(_make_config(), IndicatorEngine())
    await strat.on_start()
    # Try trading without setting range first
    signal = await strat.on_candle("NSE:RELIANCE", _make_candle(9, 45, 2860, 2870, 2855, 2865), _empty_history())
    assert signal is None
