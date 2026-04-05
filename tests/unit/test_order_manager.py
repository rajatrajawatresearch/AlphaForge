"""Tests for OrderManager paper mode realism."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphaforge.execution.order_manager import OrderManager
from alphaforge.types import OrderRequest, OrderStatus


def _make_order(price: float = 2500.0, txn: str = "BUY") -> OrderRequest:
    return OrderRequest(
        tradingsymbol="RELIANCE",
        exchange="NSE",
        transaction_type=txn,
        quantity=10,
        order_type="LIMIT",
        product="MIS",
        price=price,
        strategy_name="test",
    )


@pytest.mark.asyncio
async def test_paper_fill_returns_complete():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=0, latency_range_ms=(0, 0))
    resp = await om.place(_make_order())
    assert resp.status == OrderStatus.COMPLETE
    assert resp.filled_quantity == 10
    assert resp.order_id.startswith("PAPER-")


@pytest.mark.asyncio
async def test_paper_fill_applies_slippage_buy():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=1.0, latency_range_ms=(0, 0))
    prices = []
    for _ in range(50):
        resp = await om.place(_make_order(price=1000.0, txn="BUY"))
        prices.append(resp.average_price)
    # BUY slippage should be upward
    assert all(p >= 1000.0 for p in prices)
    assert any(p > 1000.0 for p in prices)  # At least one slipped


@pytest.mark.asyncio
async def test_paper_fill_applies_slippage_sell():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=1.0, latency_range_ms=(0, 0))
    prices = []
    for _ in range(50):
        resp = await om.place(_make_order(price=1000.0, txn="SELL"))
        prices.append(resp.average_price)
    # SELL slippage should be downward
    assert all(p <= 1000.0 for p in prices)
    assert any(p < 1000.0 for p in prices)


@pytest.mark.asyncio
async def test_paper_fill_applies_latency():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=0, latency_range_ms=(50, 50))
    start = time.monotonic()
    await om.place(_make_order())
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms >= 40  # Allow small tolerance


@pytest.mark.asyncio
async def test_paper_fill_no_slippage_when_zero():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=0.0, latency_range_ms=(0, 0))
    resp = await om.place(_make_order(price=2500.0))
    assert resp.average_price == 2500.0


@pytest.mark.asyncio
async def test_order_log_accumulates():
    om = OrderManager(MagicMock(), mode="paper", slippage_pct=0, latency_range_ms=(0, 0))
    await om.place(_make_order())
    await om.place(_make_order())
    await om.place(_make_order())
    assert len(om.order_log) == 3


@pytest.mark.asyncio
async def test_live_mode_calls_client():
    mock_client = MagicMock()
    mock_client.place_order = AsyncMock(return_value="ORDER-123")
    om = OrderManager(mock_client, mode="live")
    resp = await om.place(_make_order())
    mock_client.place_order.assert_called_once()
    assert resp.order_id == "ORDER-123"
