"""Position persistence — save/load positions across restarts."""

import json
import logging
from datetime import datetime
from pathlib import Path

from ..types import Position
from ..utils.time import IST

logger = logging.getLogger("alphaforge.execution")

DEFAULT_PATH = Path("data/positions.json")


class PositionPersistence:
    """Atomic save/load of positions to JSON file."""

    def __init__(self, filepath: Path = DEFAULT_PATH):
        self.filepath = filepath

    def save(self, positions: list[Position], trade_log: list[dict], realized_pnl: float) -> None:
        """Save positions atomically (write to .tmp then rename)."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp": datetime.now(IST).isoformat(),
            "realized_pnl": realized_pnl,
            "positions": [
                {
                    "tradingsymbol": p.tradingsymbol,
                    "exchange": p.exchange,
                    "product": p.product,
                    "quantity": p.quantity,
                    "average_price": p.average_price,
                    "last_price": p.last_price,
                    "pnl": p.pnl,
                    "strategy_name": p.strategy_name,
                    "entry_time": p.entry_time.isoformat() if p.entry_time else None,
                    "stop_loss": p.stop_loss,
                    "target": p.target,
                }
                for p in positions
            ],
            "trade_log": trade_log,
        }
        tmp = self.filepath.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.rename(self.filepath)
        logger.info("Saved %d positions to %s", len(positions), self.filepath)

    def load(self) -> tuple[list[Position], list[dict], float]:
        """Load persisted positions. Returns (positions, trade_log, realized_pnl)."""
        if not self.filepath.exists():
            return [], [], 0.0

        try:
            data = json.loads(self.filepath.read_text())
            positions = [
                Position(
                    tradingsymbol=p["tradingsymbol"],
                    exchange=p["exchange"],
                    product=p.get("product", "CNC"),
                    quantity=p["quantity"],
                    average_price=p["average_price"],
                    last_price=p.get("last_price", p["average_price"]),
                    pnl=p.get("pnl", 0.0),
                    strategy_name=p.get("strategy_name", ""),
                    entry_time=datetime.fromisoformat(p["entry_time"]) if p.get("entry_time") else None,
                    stop_loss=p.get("stop_loss"),
                    target=p.get("target"),
                )
                for p in data.get("positions", [])
            ]
            trade_log = data.get("trade_log", [])
            realized_pnl = data.get("realized_pnl", 0.0)
            logger.info("Loaded %d positions from %s", len(positions), self.filepath)
            return positions, trade_log, realized_pnl
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load positions: %s", e)
            return [], [], 0.0

    def exists(self) -> bool:
        return self.filepath.exists()

    def clear(self) -> None:
        if self.filepath.exists():
            self.filepath.unlink()
            logger.info("Cleared persisted positions")
