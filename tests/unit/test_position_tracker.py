"""Tests for PositionTracker P&L tracking and callbacks."""

from datetime import datetime

from alphaforge.execution.tracker import PositionTracker
from alphaforge.types import OrderResponse, OrderStatus
from alphaforge.utils.time import IST


def _make_fill(symbol="RELIANCE", txn="BUY", qty=10, price=2500.0, strategy="test") -> OrderResponse:
    return OrderResponse(
        order_id="TEST-001",
        status=OrderStatus.COMPLETE,
        tradingsymbol=symbol,
        exchange="NSE",
        transaction_type=txn,
        quantity=qty,
        price=price,
        average_price=price,
        filled_quantity=qty,
        pending_quantity=0,
        timestamp=datetime.now(IST),
        strategy_name=strategy,
    )


def test_open_long_position():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2500))
    assert len(tracker.open_positions) == 1
    assert tracker.open_positions[0].quantity == 10


def test_open_short_position():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="SELL", qty=5, price=2500))
    assert len(tracker.open_positions) == 1
    assert tracker.open_positions[0].quantity == -5


def test_close_long_position_pnl():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2500))
    tracker.process_fill(_make_fill(txn="SELL", qty=10, price=2600))
    assert len(tracker.open_positions) == 0
    # P&L = (2600 - 2500) * 10 = 1000
    assert tracker.realized_pnl == 1000.0


def test_close_short_position_pnl():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="SELL", qty=10, price=2500))
    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2400))
    assert len(tracker.open_positions) == 0
    # P&L = (2500 - 2400) * 10 = 1000
    assert tracker.realized_pnl == 1000.0


def test_update_prices_unrealized():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2500))
    tracker.update_prices({"NSE:RELIANCE": 2600.0})
    assert tracker.unrealized_pnl == 1000.0
    assert tracker.total_pnl == 1000.0


def test_pnl_callback_fires():
    tracker = PositionTracker()
    received = []
    tracker.on_realized_pnl(lambda pnl: received.append(pnl))

    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2500))
    tracker.process_fill(_make_fill(txn="SELL", qty=10, price=2600))

    assert len(received) == 1
    assert received[0] == 1000.0


def test_total_pnl_combines():
    tracker = PositionTracker()
    # Close one trade for realized P&L
    tracker.process_fill(_make_fill(symbol="TCS", txn="BUY", qty=5, price=3000, strategy="s1"))
    tracker.process_fill(_make_fill(symbol="TCS", txn="SELL", qty=5, price=3100, strategy="s1"))
    # Open another for unrealized
    tracker.process_fill(_make_fill(symbol="INFY", txn="BUY", qty=10, price=1500, strategy="s2"))
    tracker.update_prices({"NSE:INFY": 1550.0})

    assert tracker.realized_pnl == 500.0  # (3100-3000)*5
    assert tracker.unrealized_pnl == 500.0  # (1550-1500)*10
    assert tracker.total_pnl == 1000.0


def test_trade_log():
    tracker = PositionTracker()
    tracker.process_fill(_make_fill(txn="BUY", qty=10, price=2500))
    tracker.process_fill(_make_fill(txn="SELL", qty=10, price=2600))
    assert len(tracker.trade_log) == 1
    assert tracker.trade_log[0]["pnl"] == 1000.0
