"""AlphaForge application orchestrator — wires all components together."""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from .broker.auth import authenticate
from .broker.client import KiteClient
from .broker.rate_limiter import RateLimiter
from .broker.ticker import AsyncTicker
from .config import load_config
from .data.candle_builder import CandleBuilder
from .data.feed import DataFeed
from .data.instruments import InstrumentManager
from .data.store import DataStore
from .execution.order_manager import OrderManager
from .execution.tracker import PositionTracker
from .execution.trail_stop import TrailingStopManager
from .indicators.engine import IndicatorEngine
from .risk.kill_switch import KillSwitch
from .risk.manager import RiskManager
from .strategy.momentum_scalper import MomentumScalperStrategy
from .strategy.orb import ORBStrategy
from .strategy.registry import StrategyRegistry
from .strategy.runner import StrategyRunner
from .strategy.vwap_reversion import VWAPReversionStrategy
from .types import OrderRequest, RiskRejection
from .utils.errors import AuthError, ConfigError
from .utils.logging import setup_logging
from .utils.time import is_market_open, is_trading_day, now_ist

logger = logging.getLogger("alphaforge")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaForge Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live", "stream-test", "backtest"], default=None)
    parser.add_argument("--config", default="config/settings.toml")
    parser.add_argument("--dashboard", action="store_true", help="Launch monitoring dashboard")
    return parser.parse_args()


async def run_trading_loop(config, kite, mode: str, launch_dashboard: bool) -> None:
    """Main async trading loop — connects all components."""
    shutdown_event = asyncio.Event()

    # Handle Ctrl+C gracefully
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    # Initialize components
    rate_limiter = RateLimiter()
    client = KiteClient(kite, rate_limiter)
    indicator_engine = IndicatorEngine()
    store = DataStore(client)

    # Instrument manager
    instruments = InstrumentManager(client)
    await instruments.load(["NSE", "NFO"])

    # Risk components
    kill_switch = KillSwitch(client, config.risk.initial_capital, config.risk.daily_loss_limit_pct)
    risk_manager = RiskManager(config.risk, kill_switch)

    # Execution
    order_manager = OrderManager(client, mode=mode)
    position_tracker = PositionTracker()
    trail_stop = TrailingStopManager(client, config.risk.trailing_stop_atr_multiplier)

    # Strategy registry
    registry = StrategyRegistry()
    if config.strategies.orb.enabled:
        registry.register(ORBStrategy(config.strategies.orb, indicator_engine))
    if config.strategies.vwap_reversion.enabled:
        registry.register(VWAPReversionStrategy(config.strategies.vwap_reversion))
    if config.strategies.momentum_scalper.enabled:
        registry.register(MomentumScalperStrategy(config.strategies.momentum_scalper, indicator_engine))

    # AI strategies (optional — require API keys)
    try:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key and config.strategies.news_sentiment.enabled:
            from .ai.sentiment import SentimentAnalyzer
            from .data.news.aggregator import NewsAggregator
            from .data.news.rss_reader import RSSReader
            from .strategy.news_sentiment import NewsSentimentStrategy

            analyzer = SentimentAnalyzer(anthropic_key, config.ai.anthropic_model)
            rss = RSSReader(config.news.rss_feeds)
            aggregator = NewsAggregator(rss, config.news.poll_interval_seconds)
            registry.register(NewsSentimentStrategy(config.strategies.news_sentiment, analyzer, aggregator))
    except Exception as e:
        logger.warning("News sentiment strategy skipped: %s", e)

    try:
        if config.strategies.swing_ml.enabled:
            from .ai.ensemble import EnsembleScorer
            from .ai.feature_engine import FeatureEngine
            from .ai.ml_predictor import MLPredictor
            from .strategy.swing_ml import SwingMLStrategy

            predictor = MLPredictor()
            feature_engine = FeatureEngine(indicator_engine)
            ensemble = EnsembleScorer()
            registry.register(SwingMLStrategy(config.strategies.swing_ml, predictor, feature_engine, ensemble))
    except Exception as e:
        logger.warning("Swing ML strategy skipped: %s", e)

    try:
        if config.strategies.options_decay.enabled:
            from .strategy.options_decay import OptionsDecayStrategy
            registry.register(OptionsDecayStrategy(config.strategies.options_decay, instruments))
    except Exception as e:
        logger.warning("Options decay strategy skipped: %s", e)

    # Strategy runner
    signal_queue = asyncio.Queue()
    runner = StrategyRunner(registry, signal_queue, shutdown_event)

    # WebSocket ticker
    access_token = kite.access_token
    ticker = AsyncTicker(config.broker.api_key, access_token)
    ticker.set_instrument_map(instruments.token_to_symbol_map)

    # Subscribe to required instruments
    required_symbols = registry.get_required_instruments()
    tokens = []
    for sym in required_symbols:
        parts = sym.split(":")
        exchange = parts[0] if len(parts) > 1 else "NSE"
        symbol = parts[-1]
        token = instruments.get_token(exchange, symbol)
        if token:
            tokens.append(token)

    if tokens:
        ticker.subscribe(tokens)
        logger.info("Subscribed to %d instruments", len(tokens))

    # Data feed
    feed = DataFeed(ticker, ["minute", "5minute", "15minute"])

    # Connect candles to strategy runner
    def on_candle_complete(candle):
        asyncio.create_task(runner.dispatch_candle(candle))
    feed.candle_builder.on_candle(on_candle_complete)

    # Dashboard
    if launch_dashboard:
        from .dashboard.app import DashboardApp
        dashboard = DashboardApp(config.dashboard.host, config.dashboard.port)
        shared_state = {
            "mode": mode,
            "positions": position_tracker.open_positions,
            "orders": order_manager.order_log,
            "risk_state": risk_manager.get_risk_state(),
            "kill_switch_cb": kill_switch.trigger_manual,
        }
        dashboard.start(shared_state)

    # Signal processing loop
    async def process_signals():
        while not shutdown_event.is_set():
            try:
                sig = await asyncio.wait_for(signal_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            result = risk_manager.evaluate_signal(sig)
            if isinstance(result, RiskRejection):
                logger.info("Signal rejected: %s — %s", sig.tradingsymbol, result.reason)
                continue

            # Place order
            response = await order_manager.place(result)
            position_tracker.process_fill(response)

            if launch_dashboard:
                dashboard.update_state("positions", position_tracker.open_positions)
                dashboard.update_state("orders", order_manager.order_log)
                dashboard.update_state("total_pnl", position_tracker.total_pnl)
                dashboard.update_state("realized_pnl", position_tracker.realized_pnl)
                dashboard.update_state("unrealized_pnl", position_tracker.unrealized_pnl)

    # Start everything
    logger.info("Starting trading loop...")
    await ticker.start()

    tasks = [
        asyncio.create_task(feed.run(shutdown_event), name="data-feed"),
        asyncio.create_task(runner.run(), name="strategy-runner"),
        asyncio.create_task(process_signals(), name="signal-processor"),
        asyncio.create_task(kill_switch.run(shutdown_event), name="kill-switch"),
    ]

    # Wait for shutdown
    await shutdown_event.wait()
    logger.info("Shutdown signal received — stopping...")

    # Cancel tasks
    for task in tasks:
        task.cancel()

    await ticker.stop()
    logger.info("AlphaForge stopped. Final P&L: ₹%.2f", position_tracker.total_pnl)


def main() -> None:
    """Main entry point for AlphaForge."""
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    if project_root.exists():
        os.chdir(project_root)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"\n  [ERROR] {e}")
        print("  Copy .env.example to .env and fill in your credentials.\n")
        sys.exit(1)

    mode = args.mode or config.app.mode
    setup_logging(level=config.app.log_level)

    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║         ALPHAFORGE TRADING BOT            ║")
    print("  ║   AI-Powered • Multi-Strategy • NSE/BSE   ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()
    logger.info("AlphaForge v0.1.0 starting in %s mode", mode.upper())

    now = now_ist()
    if is_trading_day(now):
        logger.info("Market %s — %s IST",
                     "OPEN" if is_market_open(now) else "CLOSED",
                     now.strftime("%H:%M:%S"))
    else:
        logger.info("Non-trading day — %s", now.strftime("%A, %Y-%m-%d"))

    try:
        kite = authenticate(config.broker.api_key, config.broker.api_secret)
    except AuthError as e:
        logger.error("Authentication failed: %s", e)
        sys.exit(1)

    logger.info("Session established | Capital: ₹%.0f | Max positions: %d",
                config.risk.initial_capital, config.risk.max_concurrent_positions)

    strategies = config.strategies
    enabled = []
    for name, cfg in [("ORB", strategies.orb), ("VWAP", strategies.vwap_reversion),
                       ("Momentum", strategies.momentum_scalper), ("Options", strategies.options_decay),
                       ("News/LLM", strategies.news_sentiment), ("SwingML", strategies.swing_ml)]:
        if cfg.enabled:
            enabled.append(name)
    logger.info("Strategies: %s", ", ".join(enabled) or "None")

    if mode == "live":
        logger.warning("LIVE MODE — Real orders will be placed!")

    # Run the async trading loop
    try:
        asyncio.run(run_trading_loop(config, kite, mode, args.dashboard))
    except KeyboardInterrupt:
        print("\n  AlphaForge stopped by user.\n")


if __name__ == "__main__":
    main()
