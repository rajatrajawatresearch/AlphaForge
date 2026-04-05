"""Daily report generation."""

import json
import logging
from datetime import datetime
from pathlib import Path

from ..execution.tracker import PositionTracker
from ..risk.manager import RiskManager
from ..utils.time import IST

logger = logging.getLogger("alphaforge.reports")

REPORTS_DIR = Path("data/reports")


class DailyReport:
    """Generates end-of-day performance reports."""

    def __init__(self, output_dir: Path = REPORTS_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, tracker: PositionTracker, risk_manager: RiskManager, config) -> dict:
        """Collect all metrics into a report dict."""
        trade_log = tracker.trade_log
        pnls = [t.get("pnl", 0) for t in trade_log]
        wins = sum(1 for p in pnls if p > 0)

        return {
            "date": datetime.now(IST).strftime("%Y-%m-%d"),
            "total_pnl": tracker.total_pnl,
            "realized_pnl": tracker.realized_pnl,
            "unrealized_pnl": tracker.unrealized_pnl,
            "total_trades": len(trade_log),
            "win_rate_pct": (wins / len(pnls) * 100) if pnls else 0,
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
            "open_positions": len(tracker.open_positions),
            "risk_state": risk_manager.get_risk_state(),
            "initial_capital": config.risk.initial_capital,
            "trade_log": trade_log,
        }

    def save_json(self, report: dict) -> Path:
        date_str = report.get("date", datetime.now(IST).strftime("%Y-%m-%d"))
        path = self.output_dir / f"report_{date_str}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        logger.info("Daily report saved: %s", path)
        return path

    def save_text(self, report: dict) -> Path:
        date_str = report.get("date", datetime.now(IST).strftime("%Y-%m-%d"))
        path = self.output_dir / f"report_{date_str}.txt"

        lines = [
            f"AlphaForge Daily Report — {date_str}",
            "=" * 50,
            f"Total P&L:     {report['total_pnl']:+,.2f}",
            f"Realized:      {report['realized_pnl']:+,.2f}",
            f"Unrealized:    {report['unrealized_pnl']:+,.2f}",
            f"Total Trades:  {report['total_trades']}",
            f"Win Rate:      {report['win_rate_pct']:.1f}%",
            f"Best Trade:    {report['best_trade']:+,.2f}",
            f"Worst Trade:   {report['worst_trade']:+,.2f}",
            f"Open Positions: {report['open_positions']}",
            "=" * 50,
        ]
        path.write_text("\n".join(lines))
        logger.info("Daily report text saved: %s", path)
        return path
