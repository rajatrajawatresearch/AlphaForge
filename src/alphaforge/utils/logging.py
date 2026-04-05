"""Structured logging setup for AlphaForge."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """JSON log formatter for file output."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        # Include extra context if present
        if hasattr(record, "context"):
            log_entry["context"] = record.context
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry)


class ConsoleFormatter(logging.Formatter):
    """Colored console formatter."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[1;31m",  # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        return f"{color}{timestamp} [{record.levelname:>8}] {record.module}: {record.getMessage()}{self.RESET}"


def setup_logging(level: str = "INFO", log_dir: str = "data/logs") -> logging.Logger:
    """Configure structured logging with console and file handlers.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory for log files.

    Returns:
        Root logger instance.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("alphaforge")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    console.setLevel(logging.DEBUG)
    logger.addHandler(console)

    # Main log file (JSON)
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(log_path / f"app_{date_str}.log")
    file_handler.setFormatter(JSONFormatter())
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Error log file (WARNING+)
    error_handler = logging.FileHandler(log_path / f"errors_{date_str}.log")
    error_handler.setFormatter(JSONFormatter())
    error_handler.setLevel(logging.WARNING)
    logger.addHandler(error_handler)

    # Orders log file
    orders_logger = logging.getLogger("alphaforge.orders")
    orders_handler = logging.FileHandler(log_path / f"orders_{date_str}.log")
    orders_handler.setFormatter(JSONFormatter())
    orders_logger.addHandler(orders_handler)

    # Risk log file
    risk_logger = logging.getLogger("alphaforge.risk")
    risk_handler = logging.FileHandler(log_path / f"risk_{date_str}.log")
    risk_handler.setFormatter(JSONFormatter())
    risk_logger.addHandler(risk_handler)

    return logger
