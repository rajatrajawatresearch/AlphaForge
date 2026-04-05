"""AlphaForge application orchestrator."""

import argparse
import logging
import sys
from pathlib import Path

from .broker.auth import authenticate
from .config import load_config
from .utils.errors import AlphaForgeError, AuthError, ConfigError
from .utils.logging import setup_logging
from .utils.time import is_market_open, is_trading_day, now_ist

logger = logging.getLogger("alphaforge")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaForge Trading Bot")
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "stream-test", "backtest"],
        default=None,
        help="Trading mode (overrides config)",
    )
    parser.add_argument(
        "--config",
        default="config/settings.toml",
        help="Path to config file",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the monitoring dashboard",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for AlphaForge."""
    args = parse_args()

    # Change to project root
    project_root = Path(__file__).resolve().parent.parent.parent
    if project_root.exists():
        import os
        os.chdir(project_root)

    # Load configuration
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"\n  [ERROR] {e}")
        print("  Make sure you have a .env file with KITE_API_KEY and KITE_API_SECRET")
        print("  Copy .env.example to .env and fill in your credentials.\n")
        sys.exit(1)

    # Override mode if specified
    mode = args.mode or config.app.mode

    # Setup logging
    setup_logging(level=config.app.log_level)

    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║         ALPHAFORGE TRADING BOT            ║")
    print("  ║   AI-Powered • Multi-Strategy • NSE/BSE   ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()
    logger.info("AlphaForge v0.1.0 starting in %s mode", mode.upper())

    # Market status
    now = now_ist()
    if is_trading_day(now):
        if is_market_open(now):
            logger.info("Market is OPEN — %s IST", now.strftime("%H:%M:%S"))
        else:
            logger.info("Market is CLOSED — %s IST (trading day)", now.strftime("%H:%M:%S"))
    else:
        logger.info("Today is NOT a trading day — %s", now.strftime("%A, %Y-%m-%d"))

    # Authenticate with Kite
    try:
        kite = authenticate(config.broker.api_key, config.broker.api_secret)
    except AuthError as e:
        logger.error("Authentication failed: %s", e)
        sys.exit(1)

    logger.info("Session established successfully")
    logger.info("Mode: %s | Capital: ₹%.2f | Max positions: %d",
                mode.upper(), config.risk.initial_capital, config.risk.max_concurrent_positions)

    # Log enabled strategies
    strategies = config.strategies
    enabled = []
    if strategies.orb.enabled:
        enabled.append("ORB")
    if strategies.vwap_reversion.enabled:
        enabled.append("VWAP")
    if strategies.momentum_scalper.enabled:
        enabled.append("Momentum")
    if strategies.options_decay.enabled:
        enabled.append("Options")
    if strategies.news_sentiment.enabled:
        enabled.append("News/LLM")
    if strategies.swing_ml.enabled:
        enabled.append("SwingML")

    logger.info("Enabled strategies: %s", ", ".join(enabled) if enabled else "None")

    # Phase 1 complete — authentication verified
    # Future phases will add: data pipeline, strategies, risk engine, dashboard
    logger.info("Phase 1 complete — foundation operational")

    if mode == "stream-test":
        logger.info("Stream test mode — will stream live ticks (Phase 2)")
    elif mode == "paper":
        logger.info("Paper trading mode — signals generated, no real orders")
    elif mode == "live":
        logger.warning("LIVE mode — real orders will be placed!")

    print("\n  AlphaForge is ready. (Ctrl+C to exit)\n")


if __name__ == "__main__":
    main()
