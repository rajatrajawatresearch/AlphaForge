"""Tests for candle builder."""

from datetime import datetime

from alphaforge.data.candle_builder import CandleBuilder, _align_timestamp
from alphaforge.types import Tick
from alphaforge.utils.time import IST


def _make_tick(price: float, volume: int, hour: int, minute: int, second: int = 0) -> Tick:
    return Tick(
        instrument_token=12345,
        tradingsymbol="RELIANCE",
        exchange="NSE",
        last_price=price,
        last_quantity=10,
        volume=volume,
        buy_quantity=1000,
        sell_quantity=900,
        ohlc={"open": 2800, "high": 2860, "low": 2790, "close": 2850},
        change=10.0,
        timestamp=datetime(2026, 4, 5, hour, minute, second, tzinfo=IST),
    )


def test_align_timestamp():
    dt = datetime(2026, 4, 5, 9, 17, 30, tzinfo=IST)
    aligned = _align_timestamp(dt, 900)  # 15 min
    assert aligned.hour == 9
    assert aligned.minute == 15
    assert aligned.second == 0


def test_align_timestamp_exact_boundary():
    dt = datetime(2026, 4, 5, 9, 15, 0, tzinfo=IST)
    aligned = _align_timestamp(dt, 900)
    assert aligned.hour == 9
    assert aligned.minute == 15


def test_single_tick_no_candle():
    builder = CandleBuilder(intervals=["minute"])
    tick = _make_tick(2850, 1000, 9, 15, 10)
    completed = builder.process_tick(tick)
    assert completed == []


def test_two_ticks_same_minute_no_candle():
    builder = CandleBuilder(intervals=["minute"])
    t1 = _make_tick(2850, 1000, 9, 15, 10)
    t2 = _make_tick(2860, 1200, 9, 15, 30)
    assert builder.process_tick(t1) == []
    assert builder.process_tick(t2) == []


def test_new_minute_completes_candle():
    builder = CandleBuilder(intervals=["minute"])

    # Ticks in minute 09:15
    builder.process_tick(_make_tick(2850, 1000, 9, 15, 0))
    builder.process_tick(_make_tick(2870, 1200, 9, 15, 20))
    builder.process_tick(_make_tick(2840, 1500, 9, 15, 45))

    # Tick in minute 09:16 → completes 09:15 candle
    completed = builder.process_tick(_make_tick(2855, 1800, 9, 16, 5))

    assert len(completed) == 1
    candle = completed[0]
    assert candle.open == 2850
    assert candle.high == 2870
    assert candle.low == 2840
    assert candle.close == 2840
    assert candle.tradingsymbol == "RELIANCE"
    assert candle.interval == "minute"


def test_multiple_intervals():
    builder = CandleBuilder(intervals=["minute", "5minute"])

    # Ticks in 09:15
    builder.process_tick(_make_tick(100, 500, 9, 15, 0))

    # Tick in 09:16 → completes 1-min candle but NOT 5-min
    completed = builder.process_tick(_make_tick(105, 600, 9, 16, 0))
    intervals_completed = [c.interval for c in completed]
    assert "minute" in intervals_completed
    assert "5minute" not in intervals_completed


def test_flush_all():
    builder = CandleBuilder(intervals=["minute"])
    builder.process_tick(_make_tick(2850, 1000, 9, 15, 10))
    builder.process_tick(_make_tick(2860, 1200, 9, 15, 30))

    flushed = builder.flush_all()
    assert len(flushed) == 1
    assert flushed[0].open == 2850
    assert flushed[0].high == 2860
    assert flushed[0].close == 2860


def test_callback_fired():
    builder = CandleBuilder(intervals=["minute"])
    received = []
    builder.on_candle(lambda c: received.append(c))

    builder.process_tick(_make_tick(100, 500, 9, 15, 0))
    builder.process_tick(_make_tick(110, 600, 9, 16, 0))

    assert len(received) == 1
    assert received[0].open == 100
