"""IST time helpers, market hours checks, and trading calendar."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from ..constants import (
    INTRADAY_EXIT_HOUR,
    INTRADAY_EXIT_MINUTE,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    PRE_MARKET_OPEN_HOUR,
    PRE_MARKET_OPEN_MINUTE,
)

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
MARKET_CLOSE = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
PRE_MARKET_OPEN = time(PRE_MARKET_OPEN_HOUR, PRE_MARKET_OPEN_MINUTE)
INTRADAY_EXIT = time(INTRADAY_EXIT_HOUR, INTRADAY_EXIT_MINUTE)

# NSE holidays 2026 (update annually)
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-10",  # Maha Shivaratri
    "2026-03-17",  # Holi
    "2026-03-30",  # Id-Ul-Fitr
    "2026-04-02",  # Ram Navami
    "2026-04-03",  # Mahavir Jayanti
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-04-18",  # Good Friday
    "2026-05-01",  # Maharashtra Day
    "2026-06-06",  # Id-Ul-Adha (Bakri Id)
    "2026-07-06",  # Muharram
    "2026-08-15",  # Independence Day
    "2026-08-26",  # Janmashtami
    "2026-09-04",  # Milad-un-Nabi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-09",  # Diwali (Laxmi Pujan)
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-30",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}


def now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_market_open(dt: datetime | None = None) -> bool:
    """Check if the market is currently open."""
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    t = dt.time()
    return MARKET_OPEN <= t < MARKET_CLOSE and is_trading_day(dt)


def is_pre_market(dt: datetime | None = None) -> bool:
    """Check if we're in the pre-market window (09:00-09:15 IST)."""
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    t = dt.time()
    return PRE_MARKET_OPEN <= t < MARKET_OPEN and is_trading_day(dt)


def is_intraday_exit_time(dt: datetime | None = None) -> bool:
    """Check if it's time to exit intraday positions (15:15 IST)."""
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.time() >= INTRADAY_EXIT


def is_trading_day(dt: datetime | None = None) -> bool:
    """Check if the given date is a trading day (not weekend, not holiday)."""
    dt = dt or now_ist()
    # Weekend check
    if dt.weekday() >= 5:
        return False
    # Holiday check
    date_str = dt.strftime("%Y-%m-%d")
    return date_str not in NSE_HOLIDAYS_2026


def market_open_today() -> datetime:
    """Get today's market open time in IST."""
    today = now_ist().date()
    return datetime.combine(today, MARKET_OPEN, tzinfo=IST)


def market_close_today() -> datetime:
    """Get today's market close time in IST."""
    today = now_ist().date()
    return datetime.combine(today, MARKET_CLOSE, tzinfo=IST)
