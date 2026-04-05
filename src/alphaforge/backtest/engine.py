"""Event-driven backtesting engine."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from ..risk.manager import RiskManager
from ..risk.kill_switch import KillSwitch
from ..risk.position_sizer import PositionSizer
from ..config.schema import RiskSection, StrategyLimit
from ..strategy.base import BaseStrategy
from ..types import Candle, OrderRequest, Signal, SignalType
from .metrics import compute_all_metrics

logger = logging.getLogger("alphaforge.backtest")


@dataclass
class SimulatedFill:
    tradingsymbol: str
    exchange: str
    transaction_type: str
    quantity: int
    fill_price: float
    timestamp: datetime
    strategy_name: str
    slippage: float = 0.0
    commission: float = 0.0


class SimulatedBroker:
    """Simulates order execution with slippage and commission."""

    def __init__(self, slippage_pct: float = 0.05, commission_per_order: float = 20.0):
        self.slippage_pct = slippage_pct / 100.0
        self.commission = commission_per_order

    def execute(self, order: OrderRequest, candle: Candle) -> SimulatedFill:
        """Simulate filling an order at current candle price with slippage."""
        base_price = order.price or candle.close

        # Apply slippage
        if order.transaction_type == "BUY":
            fill_price = base_price * (1 + self.slippage_pct)
        else:
            fill_price = base_price * (1 - self.slippage_pct)

        return SimulatedFill(
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            transaction_type=order.transaction_type,
            quantity=order.quantity,
            fill_price=round(fill_price, 2),
            timestamp=candle.timestamp,
            strategy_name=order.strategy_name,
            slippage=abs(fill_price - base_price) * order.quantity,
            commission=self.commission,
        )


@dataclass
class BacktestPosition:
    tradingsymbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    strategy_name: str
    stop_loss: float = 0.0
    target: float = 0.0


class BacktestEngine:
    """Event-driven backtester that reuses production strategy code."""

    def __init__(
        self,
        initial_capital: float = 500000.0,
        slippage_pct: float = 0.05,
        commission: float = 20.0,
    ):
        self.initial_capital = initial_capital
        self.broker = SimulatedBroker(slippage_pct, commission)
        self.capital = initial_capital
        self.positions: dict[str, BacktestPosition] = {}
        self.trade_pnls: list[float] = []
        self.equity_curve: list[float] = [initial_capital]
        self.equity_dates: list[datetime] = []
        self.trade_log: list[dict] = []

    async def run(
        self,
        strategy: BaseStrategy,
        data: dict[str, pd.DataFrame],
        interval: str = "15minute",
    ) -> dict:
        """Run backtest for a single strategy.

        Args:
            strategy: Strategy instance to test.
            data: Dict of symbol → OHLCV DataFrame.
            interval: Candle interval to simulate.

        Returns:
            Performance metrics dict.
        """
        await strategy.on_start()

        # Merge all symbol data into chronological order
        all_candles = []
        for symbol, df in data.items():
            for _, row in df.iterrows():
                candle = Candle(
                    timestamp=row["timestamp"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=int(row["volume"]),
                    tradingsymbol=symbol.split(":")[-1],
                    exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
                    interval=interval,
                )
                all_candles.append((row["timestamp"], symbol, candle))

        all_candles.sort(key=lambda x: x[0])

        # History buffers per symbol
        histories: dict[str, pd.DataFrame] = {}
        last_date = None

        for timestamp, symbol, candle in all_candles:
            # Track equity curve daily
            current_date = candle.timestamp
            if hasattr(current_date, 'date'):
                current_date = current_date.date() if hasattr(current_date, 'date') else current_date
            if last_date is None or current_date != last_date:
                equity = self._compute_equity(data)
                self.equity_curve.append(equity)
                if hasattr(candle.timestamp, 'date'):
                    self.equity_dates.append(candle.timestamp)
                last_date = current_date

            # Update history
            row = {
                "timestamp": candle.timestamp,
                "open": candle.open, "high": candle.high,
                "low": candle.low, "close": candle.close,
                "volume": candle.volume,
            }
            if symbol not in histories:
                histories[symbol] = pd.DataFrame(columns=row.keys())
            histories[symbol] = pd.concat(
                [histories[symbol], pd.DataFrame([row])], ignore_index=True,
            ).tail(500)

            # Check stop-loss / target hits
            self._check_exits(candle, symbol)

            # Get strategy signal
            try:
                signal = await strategy.on_candle(symbol, candle, histories[symbol])
            except Exception as e:
                logger.debug("Strategy error on %s: %s", symbol, e)
                continue

            if signal and signal.signal_type != SignalType.HOLD:
                self._process_signal(signal, candle)

        # Close all remaining positions at last price
        self._close_all_positions(all_candles)

        await strategy.on_stop()

        # Build results
        equity_series = pd.Series(self.equity_curve)
        metrics = compute_all_metrics(equity_series, self.trade_pnls)
        metrics["strategy"] = strategy.name
        metrics["initial_capital"] = self.initial_capital
        metrics["final_capital"] = self.equity_curve[-1] if self.equity_curve else self.initial_capital

        return metrics

    def _process_signal(self, signal: Signal, candle: Candle) -> None:
        """Process a signal: check if we can take the trade, simulate fill."""
        key = f"{signal.exchange}:{signal.tradingsymbol}"

        # Don't double up
        if key in self.positions:
            return

        # Simple position sizing: use 2% risk
        risk_per_share = abs(signal.suggested_price - signal.stop_loss)
        if risk_per_share <= 0:
            return
        risk_amount = self.capital * 0.02
        quantity = int(risk_amount / risk_per_share)
        if quantity <= 0:
            return

        # Simulate fill
        order = OrderRequest(
            tradingsymbol=signal.tradingsymbol,
            exchange=signal.exchange,
            transaction_type=signal.signal_type,
            quantity=quantity,
            order_type="MARKET",
            product=signal.product,
            price=signal.suggested_price,
            strategy_name=signal.strategy_name,
        )
        fill = self.broker.execute(order, candle)

        # Record position
        self.positions[key] = BacktestPosition(
            tradingsymbol=signal.tradingsymbol,
            quantity=quantity if signal.signal_type == SignalType.BUY else -quantity,
            entry_price=fill.fill_price,
            entry_time=candle.timestamp,
            strategy_name=signal.strategy_name,
            stop_loss=signal.stop_loss,
            target=signal.target,
        )
        self.capital -= fill.commission

    def _check_exits(self, candle: Candle, symbol: str) -> None:
        """Check if any position's SL or target is hit."""
        key = f"{candle.exchange}:{candle.tradingsymbol}"
        if symbol.startswith(candle.exchange):
            key = symbol

        pos = self.positions.get(key)
        if not pos:
            return

        if pos.quantity > 0:  # Long
            if candle.low <= pos.stop_loss:
                self._close_position(key, pos.stop_loss, candle.timestamp, "stop_loss")
            elif pos.target > 0 and candle.high >= pos.target:
                self._close_position(key, pos.target, candle.timestamp, "target")
        elif pos.quantity < 0:  # Short
            if candle.high >= pos.stop_loss:
                self._close_position(key, pos.stop_loss, candle.timestamp, "stop_loss")
            elif pos.target > 0 and candle.low <= pos.target:
                self._close_position(key, pos.target, candle.timestamp, "target")

    def _close_position(self, key: str, exit_price: float, timestamp: datetime, reason: str) -> None:
        pos = self.positions.pop(key, None)
        if not pos:
            return

        if pos.quantity > 0:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * abs(pos.quantity)

        pnl -= self.broker.commission  # Exit commission
        self.capital += pnl
        self.trade_pnls.append(pnl)

        self.trade_log.append({
            "symbol": pos.tradingsymbol,
            "strategy": pos.strategy_name,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.quantity,
            "pnl": pnl,
            "reason": reason,
            "entry_time": pos.entry_time,
            "exit_time": timestamp,
        })

    def _close_all_positions(self, all_candles: list) -> None:
        """Close remaining positions at last available price."""
        last_prices = {}
        for _, symbol, candle in reversed(all_candles):
            key = f"{candle.exchange}:{candle.tradingsymbol}"
            if key not in last_prices:
                last_prices[key] = candle.close

        for key in list(self.positions.keys()):
            price = last_prices.get(key, self.positions[key].entry_price)
            self._close_position(key, price, all_candles[-1][2].timestamp if all_candles else datetime.now(), "end_of_backtest")

    def _compute_equity(self, data: dict[str, pd.DataFrame]) -> float:
        """Compute current equity (capital + unrealized P&L)."""
        equity = self.capital
        for key, pos in self.positions.items():
            # Use entry price as estimate (simplified)
            equity += pos.quantity * pos.entry_price
        return equity
