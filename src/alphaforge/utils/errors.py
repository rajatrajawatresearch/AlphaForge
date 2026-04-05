"""Custom exception hierarchy for AlphaForge."""


class AlphaForgeError(Exception):
    """Base exception for all AlphaForge errors."""


class ConfigError(AlphaForgeError):
    """Configuration loading or validation error."""


class BrokerError(AlphaForgeError):
    """Broker communication error."""


class AuthError(BrokerError):
    """Authentication failure."""


class OrderError(BrokerError):
    """Order placement, modification, or cancellation error."""


class RateLimitError(BrokerError):
    """API rate limit exceeded."""


class DataError(AlphaForgeError):
    """Data fetching, storage, or processing error."""


class RiskViolation(AlphaForgeError):
    """Risk limit breach."""


class KillSwitchTriggered(AlphaForgeError):
    """Kill switch activated — all trading halted."""


class StrategyError(AlphaForgeError):
    """Error within a trading strategy."""
