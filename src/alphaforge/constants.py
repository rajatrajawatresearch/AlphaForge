"""Exchange codes, order types, market hours, and other constants."""

from enum import StrEnum

# Exchanges
class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    CDS = "CDS"
    MCX = "MCX"

# Order types
class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SL-M"

# Order varieties
class Variety(StrEnum):
    REGULAR = "regular"
    BO = "bo"
    CO = "co"
    AMO = "amo"

# Products
class Product(StrEnum):
    CNC = "CNC"      # Cash and carry (delivery)
    MIS = "MIS"      # Margin intraday
    NRML = "NRML"    # Normal (F&O overnight)

# Transaction types
class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

# Validity
class Validity(StrEnum):
    DAY = "DAY"
    IOC = "IOC"

# Candle intervals
class Interval(StrEnum):
    MINUTE = "minute"
    MINUTE_3 = "3minute"
    MINUTE_5 = "5minute"
    MINUTE_10 = "10minute"
    MINUTE_15 = "15minute"
    MINUTE_30 = "30minute"
    MINUTE_60 = "60minute"
    DAY = "day"

# Market hours (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
PRE_MARKET_OPEN_HOUR = 9
PRE_MARKET_OPEN_MINUTE = 0

# Intraday square-off time
INTRADAY_EXIT_HOUR = 15
INTRADAY_EXIT_MINUTE = 15

# Rate limits
API_RATE_LIMIT_PER_SECOND = 10
ORDER_RATE_LIMIT_PER_MINUTE = 200

# WebSocket
WS_MAX_INSTRUMENTS_PER_CONNECTION = 3000
WS_MAX_CONNECTIONS = 3
