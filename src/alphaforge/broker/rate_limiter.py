"""Token bucket rate limiter for Kite Connect API."""

import asyncio
import time


class TokenBucket:
    """Token bucket algorithm for rate limiting."""

    def __init__(self, rate: float, capacity: int):
        """Initialize bucket.

        Args:
            rate: Tokens added per second.
            capacity: Maximum tokens in bucket.
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                # Compute wait time for next token
                wait = (1.0 - self.tokens) / self.rate
            await asyncio.sleep(wait)


class RateLimiter:
    """Manages multiple rate limit buckets for Kite API."""

    def __init__(self):
        # General API: 10 requests/second
        self.general = TokenBucket(rate=10.0, capacity=10)
        # Order API: 200 orders/minute (~3.33/second)
        self.orders = TokenBucket(rate=200.0 / 60.0, capacity=10)

    async def acquire_general(self) -> None:
        """Acquire a token for general API calls."""
        await self.general.acquire()

    async def acquire_order(self) -> None:
        """Acquire a token for order placement (checks both buckets)."""
        await self.general.acquire()
        await self.orders.acquire()
