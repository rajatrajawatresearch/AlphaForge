#!/usr/bin/env python3
"""Run backtests from command line."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from alphaforge.backtest.data_loader import BacktestDataLoader
from alphaforge.backtest.engine import BacktestEngine
from alphaforge.config import load_config
from alphaforge.data.store import DataStore
from alphaforge.indicators.engine import IndicatorEngine
from alphaforge.strategy.orb import ORBStrategy
from alphaforge.strategy.vwap_reversion import VWAPReversionStrategy
from alphaforge.strategy.momentum_scalper import MomentumScalperStrategy
from alphaforge.utils.logging import setup_logging

STRATEGY_MAP = {
    "orb": lambda cfg: ORBStrategy(cfg.strategies.orb, IndicatorEngine()),
    "vwap": lambda cfg: VWAPReversionStrategy(cfg.strategies.vwap_reversion),
    "momentum": lambda cfg: MomentumScalperStrategy(cfg.strategies.momentum_scalper, IndicatorEngine()),
}

STRATEGY_INTERVALS = {
    "orb": "15minute",
    "vwap": "5minute",
    "momentum": "minute",
}


async def backtest(args):
    config = load_config()
    setup_logging(level="INFO")

    store = DataStore()
    loader = BacktestDataLoader(store)

    strategy_name = args.strategy
    if strategy_name not in STRATEGY_MAP:
        print(f"Unknown strategy: {strategy_name}")
        print(f"Available: {', '.join(STRATEGY_MAP.keys())}")
        sys.exit(1)

    strategy = STRATEGY_MAP[strategy_name](config)
    interval = STRATEGY_INTERVALS.get(strategy_name, "15minute")

    symbols = [f"NSE:{s}" for s in args.symbols]
    print(f"\nBacktest: {strategy_name.upper()}")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Period: {args.start} to {args.end}")
    print(f"Interval: {interval}")
    print(f"Capital: ₹{args.capital:,.0f}")
    print()

    data = loader.load(symbols, interval=interval, start_date=args.start, end_date=args.end)
    if not data:
        print("No data available. Run download_history.py first.")
        sys.exit(1)

    engine = BacktestEngine(initial_capital=args.capital)
    metrics = await engine.run(strategy, data, interval)

    print("=" * 50)
    print(f"  BACKTEST RESULTS: {strategy_name.upper()}")
    print("=" * 50)
    print(f"  Total Return:     {metrics['total_return_pct']:+.2f}%")
    print(f"  Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio:    {metrics['sortino_ratio']:.2f}")
    print(f"  Max Drawdown:     {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate:         {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit Factor:    {metrics['profit_factor']:.2f}")
    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Avg Trade P&L:    ₹{metrics['avg_trade_pnl']:.2f}")
    print(f"  Best Trade:       ₹{metrics['best_trade']:.2f}")
    print(f"  Worst Trade:      ₹{metrics['worst_trade']:.2f}")
    print(f"  Final Capital:    ₹{metrics['final_capital']:,.2f}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Run strategy backtest")
    parser.add_argument("--strategy", required=True, choices=list(STRATEGY_MAP.keys()))
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=500000, help="Initial capital")
    args = parser.parse_args()
    asyncio.run(backtest(args))


if __name__ == "__main__":
    main()
