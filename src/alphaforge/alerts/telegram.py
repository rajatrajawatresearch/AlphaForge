"""Telegram alerting for trade events."""

import logging

import aiohttp

from ..types import OrderResponse, Signal

logger = logging.getLogger("alphaforge.alerts")


class TelegramAlerter:
    """Sends trading alerts via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def send(self, message: str) -> None:
        """Send a message. Never raises — alerting must not crash the bot."""
        if not self.enabled or not self.bot_token:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self._url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                })
        except Exception as e:
            logger.error("Telegram send error: %s", e)

    async def send_trade_entry(self, order: OrderResponse, signal: Signal | None = None) -> None:
        msg = (
            f"<b>TRADE ENTRY</b>\n"
            f"{order.transaction_type} {order.exchange}:{order.tradingsymbol} "
            f"x{order.quantity} @ {order.average_price:,.2f}\n"
            f"Strategy: {order.strategy_name}"
        )
        if signal:
            msg += f"\nSL: {signal.stop_loss:,.2f} | Target: {signal.target:,.2f}"
        await self.send(msg)

    async def send_trade_exit(self, symbol: str, pnl: float, strategy: str) -> None:
        emoji = "+" if pnl >= 0 else ""
        await self.send(
            f"<b>TRADE EXIT</b>\n"
            f"{symbol} | P&L: {emoji}{pnl:,.2f}\n"
            f"Strategy: {strategy}"
        )

    async def send_kill_switch(self, reason: str) -> None:
        await self.send(f"<b>KILL SWITCH ACTIVATED</b>\n{reason}")

    async def send_error(self, error: str) -> None:
        await self.send(f"<b>ERROR</b>\n{error}")

    async def send_daily_summary(self, summary: dict) -> None:
        msg = (
            f"<b>DAILY SUMMARY</b>\n"
            f"P&L: {summary.get('total_pnl', 0):+,.2f}\n"
            f"Trades: {summary.get('total_trades', 0)} | "
            f"Win Rate: {summary.get('win_rate_pct', 0):.0f}%\n"
            f"Realized: {summary.get('realized_pnl', 0):+,.2f} | "
            f"Unrealized: {summary.get('unrealized_pnl', 0):+,.2f}"
        )
        await self.send(msg)
