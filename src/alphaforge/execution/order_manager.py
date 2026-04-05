"""Order management — places, tracks, and simulates orders."""

import asyncio
import logging
from datetime import datetime

from ..broker.client import KiteClient
from ..types import OrderRequest, OrderResponse, OrderStatus
from ..utils.time import IST

logger = logging.getLogger("alphaforge.orders")


class OrderManager:
    """Handles order placement in both live and paper modes."""

    def __init__(self, client: KiteClient, mode: str = "paper"):
        self.client = client
        self.mode = mode
        self._order_log: list[OrderResponse] = []
        self._paper_counter = 0

    async def place(self, order: OrderRequest) -> OrderResponse:
        """Place an order (live or paper)."""
        if self.mode == "paper":
            return self._paper_fill(order)

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

    def _paper_fill(self, order: OrderRequest) -> OrderResponse:
        """Simulate an instant fill for paper trading."""
        self._paper_counter += 1
        fill_price = order.price or 0.0

        response = OrderResponse(
            order_id=f"PAPER-{self._paper_counter:06d}",
            status=OrderStatus.COMPLETE,
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            price=fill_price,
            average_price=fill_price,
            filled_quantity=order.quantity,
            pending_quantity=0,
            timestamp=datetime.now(IST),
            strategy_name=order.strategy_name,
            tag=order.tag,
        )
        self._order_log.append(response)

        logger.info("[PAPER] %s %s %s x%d @ %.2f | Strategy: %s",
                     order.transaction_type, order.exchange, order.tradingsymbol,
                     order.quantity, fill_price, order.strategy_name)
        return response

    @property
    def order_log(self) -> list[OrderResponse]:
        return list(self._order_log)

    def get_order(self, order_id: str) -> OrderResponse | None:
        for o in self._order_log:
            if o.order_id == order_id:
                return o
        return None
