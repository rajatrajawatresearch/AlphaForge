"""KiteClient wrapper with rate limiting and retry logic."""

import asyncio
import logging
from datetime import datetime
from functools import partial

from kiteconnect import KiteConnect

from ..constants import Exchange, OrderType, Product, TransactionType, Validity, Variety
from ..types import OrderRequest, OrderResponse, OrderStatus, Position
from ..utils.errors import BrokerError, OrderError, RateLimitError
from .rate_limiter import RateLimiter

logger = logging.getLogger("alphaforge.broker")


class KiteClient:
    """Async-friendly wrapper around KiteConnect with rate limiting and retries."""

    def __init__(self, kite: KiteConnect, rate_limiter: RateLimiter | None = None):
        self.kite = kite
        self.rate_limiter = rate_limiter or RateLimiter()
        self._loop = asyncio.get_event_loop()

    async def _call(self, func, *args, **kwargs):
        """Execute a blocking Kite API call in the thread pool with rate limiting."""
        await self.rate_limiter.acquire_general()
        try:
            return await self._loop.run_in_executor(None, partial(func, *args, **kwargs))
        except Exception as e:
            err_str = str(e).lower()
            if "too many requests" in err_str or "429" in err_str:
                raise RateLimitError(f"Rate limited: {e}") from e
            raise BrokerError(f"API error: {e}") from e

    async def _call_with_retry(self, func, *args, retries: int = 3, **kwargs):
        """Execute API call with exponential backoff retry."""
        last_err = None
        for attempt in range(retries):
            try:
                return await self._call(func, *args, **kwargs)
            except RateLimitError as e:
                last_err = e
                wait = min(2 ** attempt * 2, 30)
                logger.warning("Rate limited, retrying in %ds (attempt %d/%d)", wait, attempt + 1, retries)
                await asyncio.sleep(wait)
            except BrokerError as e:
                last_err = e
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning("API error, retrying in %ds: %s", wait, e)
                    await asyncio.sleep(wait)
        raise last_err

    # ── Market Data ──

    async def get_quote(self, instruments: list[str]) -> dict:
        """Get full quotes. instruments: ["NSE:RELIANCE", "NFO:NIFTY..."]"""
        return await self._call_with_retry(self.kite.quote, instruments)

    async def get_ohlc(self, instruments: list[str]) -> dict:
        return await self._call_with_retry(self.kite.ohlc, instruments)

    async def get_ltp(self, instruments: list[str]) -> dict:
        return await self._call_with_retry(self.kite.ltp, instruments)

    async def get_instruments(self, exchange: str | None = None) -> list[dict]:
        if exchange:
            return await self._call_with_retry(self.kite.instruments, exchange)
        return await self._call_with_retry(self.kite.instruments)

    async def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime | str,
        to_date: datetime | str,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list:
        return await self._call_with_retry(
            self.kite.historical_data,
            instrument_token, from_date, to_date, interval,
            continuous=continuous, oi=oi,
        )

    # ── Orders ──

    async def place_order(self, order: OrderRequest) -> str:
        """Place an order. Returns order_id."""
        await self.rate_limiter.acquire_order()
        try:
            order_id = await self._loop.run_in_executor(
                None,
                partial(
                    self.kite.place_order,
                    variety=order.variety,
                    tradingsymbol=order.tradingsymbol,
                    exchange=order.exchange,
                    transaction_type=order.transaction_type,
                    quantity=order.quantity,
                    order_type=order.order_type,
                    product=order.product,
                    price=order.price,
                    trigger_price=order.trigger_price,
                    validity=order.validity,
                    tag=order.tag[:20] if order.tag else None,
                ),
            )
            logger.info("Order placed: %s %s %s x%d @ %s (id: %s)",
                        order.transaction_type, order.exchange, order.tradingsymbol,
                        order.quantity, order.price or "MARKET", order_id)
            return order_id
        except Exception as e:
            raise OrderError(f"Order placement failed: {e}") from e

    async def modify_order(self, variety: str, order_id: str, **kwargs) -> str:
        try:
            return await self._call(self.kite.modify_order, variety, order_id, **kwargs)
        except BrokerError as e:
            raise OrderError(f"Order modification failed: {e}") from e

    async def cancel_order(self, variety: str, order_id: str) -> str:
        try:
            return await self._call(self.kite.cancel_order, variety, order_id)
        except BrokerError as e:
            raise OrderError(f"Order cancellation failed: {e}") from e

    # ── Portfolio ──

    async def get_positions(self) -> dict:
        return await self._call_with_retry(self.kite.positions)

    async def get_holdings(self) -> list:
        return await self._call_with_retry(self.kite.holdings)

    async def get_orders(self) -> list:
        return await self._call_with_retry(self.kite.orders)

    async def get_order_history(self, order_id: str) -> list:
        return await self._call_with_retry(self.kite.order_history, order_id)

    async def get_margins(self, segment: str = "equity") -> dict:
        return await self._call_with_retry(self.kite.margins, segment=segment)

    # ── Helpers ──

    async def cancel_all_orders(self) -> list[str]:
        """Cancel all open/pending orders. Returns list of cancelled order_ids."""
        orders = await self.get_orders()
        cancelled = []
        for order in orders:
            if order.get("status") in ("OPEN", "TRIGGER PENDING"):
                try:
                    oid = await self.cancel_order(
                        order.get("variety", "regular"),
                        order["order_id"],
                    )
                    cancelled.append(oid)
                except OrderError as e:
                    logger.error("Failed to cancel order %s: %s", order["order_id"], e)
        return cancelled

    async def square_off_all(self) -> list[str]:
        """Square off all open positions with market orders."""
        positions = await self.get_positions()
        order_ids = []
        for pos in positions.get("net", []):
            qty = pos.get("quantity", 0)
            if qty == 0:
                continue
            txn = TransactionType.SELL if qty > 0 else TransactionType.BUY
            order = OrderRequest(
                tradingsymbol=pos["tradingsymbol"],
                exchange=Exchange(pos["exchange"]),
                transaction_type=txn,
                quantity=abs(qty),
                order_type=OrderType.MARKET,
                product=Product(pos["product"]),
                tag="KILLSWITCH",
            )
            try:
                oid = await self.place_order(order)
                order_ids.append(oid)
            except OrderError as e:
                logger.error("Failed to square off %s: %s", pos["tradingsymbol"], e)
        return order_ids
