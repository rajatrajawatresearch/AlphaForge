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
from .constants import Exchange, OrderType, Product, TransactionType
from .data.feed import DataFeed
from .data.instruments import InstrumentManager
from .data.store import DataStore
from .execution.order_manager import OrderManager
from .execution.persistence import PositionPersistence
from .execution.tracker import PositionTracker
from .execution.trail_stop import TrailingStopManager
from .indicators.engine import IndicatorEngine
from .reports.daily import DailyReport
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
    pnl_history: list[dict] = []

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
    order_manager = OrderManager(
        client, mode=mode,
        slippage_pct=config.paper.slippage_pct,
        latency_range_ms=(config.paper.latency_min_ms, config.paper.latency_max_ms),
    )
    position_tracker = PositionTracker()
    trail_stop = TrailingStopManager(client, config.risk.trailing_stop_atr_multiplier)

    # Wire P&L sync: tracker → kill switch
    position_tracker.on_realized_pnl(kill_switch.add_realized_pnl)

    # Position persistence — load previous session
    persistence = PositionPersistence()
    if persistence.exists():
        saved_positions, saved_trades, saved_pnl = persistence.load()
        if saved_positions:
            logger.info("Restored %d positions from previous session", len(saved_positions))

    # Telegram alerting
    alerter = None
    if config.telegram.enabled and config.telegram.bot_token:
        from .alerts.telegram import TelegramAlerter
        alerter = TelegramAlerter(config.telegram.bot_token, config.telegram.chat_id)
        logger.info("Telegram alerting enabled")

    # Strategy registry
    registry = StrategyRegistry()
    if config.strategies.orb.enabled:
        registry.register(ORBStrategy(config.strategies.orb, indicator_engine))
    if config.strategies.vwap_reversion.enabled:
        registry.register(VWAPReversionStrategy(config.strategies.vwap_reversion))
    if config.strategies.momentum_scalper.enabled:
        registry.register(MomentumScalperStrategy(config.strategies.momentum_scalper, indicator_engine))

    # AI strategies (optional)
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
            registry.register(SwingMLStrategy(config.strategies.swing_ml, predictor, feature_engine, EnsembleScorer()))
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

    # Wire ticker health alerts
    if alerter:
        ticker.set_health_alert_callback(lambda msg: asyncio.create_task(alerter.send_error(msg)))

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
    dashboard = None
    if launch_dashboard:
        from .dashboard.app import DashboardApp
        dashboard = DashboardApp(config.dashboard.host, config.dashboard.port)
        shared_state = {
            "mode": mode,
            "positions": position_tracker.open_positions,
            "orders": order_manager.order_log,
            "risk_state": risk_manager.get_risk_state(),
            "kill_switch_cb": kill_switch.trigger_manual,
            "pnl_history": pnl_history,
            "trades_today": 0,
            "capital_used_pct": 0.0,
            "total_pnl": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
        }
        dashboard.start(shared_state)

    # Helper: update dashboard state
    def update_dashboard():
        if not dashboard:
            return
        dashboard.update_state("positions", position_tracker.open_positions)
        dashboard.update_state("orders", order_manager.order_log)
        dashboard.update_state("total_pnl", position_tracker.total_pnl)
        dashboard.update_state("realized_pnl", position_tracker.realized_pnl)
        dashboard.update_state("unrealized_pnl", position_tracker.unrealized_pnl)
        dashboard.update_state("trades_today", len(position_tracker.trade_log))
        total_capital = config.risk.initial_capital
        capital_used = sum(abs(p.quantity * p.average_price) for p in position_tracker.open_positions)
        dashboard.update_state("capital_used_pct", (capital_used / total_capital) * 100 if total_capital else 0)
        dashboard.update_state("risk_state", risk_manager.get_risk_state())

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

            response = await order_manager.place(result)
            position_tracker.process_fill(response)

            if alerter:
                await alerter.send_trade_entry(response, sig)

            update_dashboard()

    # Periodic dashboard P&L snapshot
    async def periodic_dashboard_update():
        while not shutdown_event.is_set():
            await asyncio.sleep(2.0)
            if dashboard:
                pnl_history.append({"time": now_ist().strftime("%H:%M:%S"), "pnl": position_tracker.total_pnl})
                # Keep last 2000 data points
                if len(pnl_history) > 2000:
                    pnl_history.pop(0)
                dashboard.update_state("pnl_history", list(pnl_history))
                update_dashboard()

    # Start everything
    logger.info("Starting trading loop...")
    await ticker.start()

    tasks = [
        asyncio.create_task(feed.run(shutdown_event), name="data-feed"),
        asyncio.create_task(runner.run(), name="strategy-runner"),
        asyncio.create_task(process_signals(), name="signal-processor"),
        asyncio.create_task(kill_switch.run(shutdown_event), name="kill-switch"),
        asyncio.create_task(ticker.health_monitor(shutdown_event), name="ticker-health"),
    ]
    if dashboard:
        tasks.append(asyncio.create_task(periodic_dashboard_update(), name="dashboard-updater"))

    # ═══ WAIT FOR SHUTDOWN ═══
    await shutdown_event.wait()
    logger.info("Shutdown signal received — stopping...")

    # Cancel running tasks
    for task in tasks:
        task.cancel()

    # ═══ GRACEFUL SHUTDOWN ═══
    # Square off MIS positions in live mode
    mis_positions = [p for p in position_tracker.open_positions if p.product == "MIS"]
    cnc_positions = [p for p in position_tracker.open_positions if p.product in ("CNC", "NRML")]

    if mis_positions and mode == "live":
        logger.info("Squaring off %d MIS positions...", len(mis_positions))
        for pos in mis_positions:
            txn = TransactionType.SELL if pos.quantity > 0 else TransactionType.BUY
            exit_order = OrderRequest(
                tradingsymbol=pos.tradingsymbol,
                exchange=Exchange(pos.exchange),
                transaction_type=txn,
                quantity=abs(pos.quantity),
                order_type=OrderType.MARKET,
                product=Product(pos.product),
                tag="SHUTDOWN",
                strategy_name=pos.strategy_name,
            )
            try:
                await order_manager.place(exit_order)
            except Exception as e:
                logger.error("Failed to square off %s: %s", pos.tradingsymbol, e)

    # Persist CNC/NRML positions for next session
    if cnc_positions:
        persistence.save(cnc_positions, position_tracker.trade_log, position_tracker.realized_pnl)

    # Generate daily report
    if is_trading_day(now_ist()):
        try:
            reporter = DailyReport()
            report = reporter.generate(position_tracker, risk_manager, config)
            reporter.save_json(report)
            reporter.save_text(report)
            if alerter:
                await alerter.send_daily_summary(report)
            logger.info("Daily report generated")
        except Exception as e:
            logger.error("Daily report error: %s", e)

    await ticker.stop()
    logger.info("AlphaForge stopped. Final P&L: ₹%.2f (ticks: %d, drops: %d)",
                position_tracker.total_pnl, ticker.tick_count, ticker.drop_count)


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

    try:
        asyncio.run(run_trading_loop(config, kite, mode, args.dashboard))
    except KeyboardInterrupt:
        print("\n  AlphaForge stopped by user.\n")


if __name__ == "__main__":
    main()
