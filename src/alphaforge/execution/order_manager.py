"""Order management — places, tracks, and simulates orders."""

import asyncio
import logging
import random
from datetime import datetime

from ..broker.client import KiteClient
from ..types import OrderRequest, OrderResponse, OrderStatus
from ..utils.time import IST

logger = logging.getLogger("alphaforge.orders")


class OrderManager:
    """Handles order placement in both live and paper modes."""

    def __init__(
        self,
        client: KiteClient,
        mode: str = "paper",
        slippage_pct: float = 0.05,
        latency_range_ms: tuple[int, int] = (50, 200),
    ):
        self.client = client
        self.mode = mode
        self.slippage_pct = slippage_pct
        self.latency_range_ms = latency_range_ms
        self._order_log: list[OrderResponse] = []
        self._paper_counter = 0

    async def place(self, order: OrderRequest) -> OrderResponse:
        """Place an order (live or paper)."""
        if self.mode == "paper":
            return await self._paper_fill(order)

        order_id = await self.client.place_order(order)
        response = OrderResponse(
            order_id=order_id,
            status=OrderStatus.PENDING,
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            price=order.price or 0.0,
            strategy_name=order.strategy_name,
            tag=order.tag,
        )
        self._order_log.append(response)
        return response

    async def _paper_fill(self, order: OrderRequest) -> OrderResponse:
        """Simulate a realistic fill for paper trading with slippage and latency."""
        self._paper_counter += 1
        base_price = order.price or 0.0

        # Simulate latency
        latency_ms = random.randint(*self.latency_range_ms)
        await asyncio.sleep(latency_ms / 1000.0)

        # Simulate slippage
        fill_price = self._apply_slippage(base_price, order.transaction_type)

        response = OrderResponse(
            order_id=f"PAPER-{self._paper_counter:06d}",
            status=OrderStatus.COMPLETE,
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            price=base_price,
            average_price=fill_price,
            filled_quantity=order.quantity,
            pending_quantity=0,
            timestamp=datetime.now(IST),
            strategy_name=order.strategy_name,
            tag=order.tag,
        )
        self._order_log.append(response)

        logger.info("[PAPER] %s %s %s x%d @ %.2f (req: %.2f, slip: %.2f, lat: %dms) | Strategy: %s",
                     order.transaction_type, order.exchange, order.tradingsymbol,
                     order.quantity, fill_price, base_price,
                     fill_price - base_price, latency_ms, order.strategy_name)
        return response

    def _apply_slippage(self, price: float, transaction_type: str) -> float:
        """Apply random slippage: BUY slips up, SELL slips down."""
        if price <= 0 or self.slippage_pct <= 0:
            return price
        slip = random.uniform(0, self.slippage_pct / 100.0)
        if transaction_type == "BUY":
            return round(price * (1 + slip), 2)
        return round(price * (1 - slip), 2)

    @property
    def order_log(self) -> list[OrderResponse]:
        return list(self._order_log)

    def get_order(self, order_id: str) -> OrderResponse | None:
        for o in self._order_log:
            if o.order_id == order_id:
                return o
        return None
