"""Pydantic models for configuration validation."""

from pydantic import BaseModel, Field, model_validator


class AppSection(BaseModel):
    name: str = "AlphaForge"
    mode: str = "paper"  # "paper" or "live"
    timezone: str = "Asia/Kolkata"
    log_level: str = "INFO"


class BrokerSection(BaseModel):
    api_key: str
    api_secret: str


class StrategyLimit(BaseModel):
    max_allocation_pct: float = Field(20.0, gt=0, le=100.0)
    max_positions: int = Field(3, gt=0, le=50)


class PaperSection(BaseModel):
    slippage_pct: float = 0.05
    latency_min_ms: int = 50
    latency_max_ms: int = 200


class TelegramSection(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


class RiskSection(BaseModel):
    max_capital_per_trade_pct: float = Field(2.0, gt=0, le=10.0)
    daily_loss_limit_pct: float = Field(3.0, gt=0, le=20.0)
    max_concurrent_positions: int = Field(10, gt=0, le=50)
    trailing_stop_atr_multiplier: float = 2.0
    initial_capital: float = Field(500000.0, gt=0)
    strategy_limits: dict[str, StrategyLimit] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_allocations(self) -> "RiskSection":
        if self.strategy_limits:
            total = sum(sl.max_allocation_pct for sl in self.strategy_limits.values())
            if total > 100.0:
                breakdown = ", ".join(f"{k}={v.max_allocation_pct}%" for k, v in self.strategy_limits.items())
                raise ValueError(
                    f"Strategy allocations sum to {total}% (must be <= 100%). Breakdown: {breakdown}"
                )
        return self


class ORBConfig(BaseModel):
    enabled: bool = True
    symbols: list[str] = Field(default_factory=list)
    candle_interval: str = "15minute"
    breakout_buffer_pct: float = 0.1
    stop_loss_pct: float = 0.5
    target_pct: float = 1.0
    product: str = "MIS"


class VWAPReversionConfig(BaseModel):
    enabled: bool = True
    symbols: list[str] = Field(default_factory=list)
    deviation_threshold: float = 1.5
    reversion_target_pct: float = 50.0
    product: str = "MIS"


class MomentumScalperConfig(BaseModel):
    enabled: bool = True
    symbols: list[str] = Field(default_factory=list)
    candle_interval: str = "minute"
    rsi_period: int = 7
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    product: str = "MIS"


class OptionsDecayConfig(BaseModel):
    enabled: bool = True
    underlyings: list[str] = Field(default_factory=list)
    days_to_expiry_max: int = 7
    otm_strikes_away: int = 2
    min_premium: float = 50.0
    product: str = "NRML"


class NewsSentimentConfig(BaseModel):
    enabled: bool = True
    symbols: list[str] = Field(default_factory=list)
    sentiment_threshold: float = 0.8
    max_trades_per_day: int = 3
    product: str = "CNC"


class SwingMLConfig(BaseModel):
    enabled: bool = True
    symbols: list[str] = Field(default_factory=list)
    prediction_horizon_days: int = 5
    confidence_threshold: float = 0.7
    retrain_interval_days: int = 7
    product: str = "CNC"


class StrategiesSection(BaseModel):
    orb: ORBConfig = Field(default_factory=ORBConfig)
    vwap_reversion: VWAPReversionConfig = Field(default_factory=VWAPReversionConfig)
    momentum_scalper: MomentumScalperConfig = Field(default_factory=MomentumScalperConfig)
    options_decay: OptionsDecayConfig = Field(default_factory=OptionsDecayConfig)
    news_sentiment: NewsSentimentConfig = Field(default_factory=NewsSentimentConfig)
    swing_ml: SwingMLConfig = Field(default_factory=SwingMLConfig)


class DataSection(BaseModel):
    historical_days: int = 365
    cache_format: str = "parquet"
    sqlite_path: str = "data/alphaforge.db"


class AISection(BaseModel):
    anthropic_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    sentiment_batch_size: int = 5


class NewsSection(BaseModel):
    rss_feeds: list[str] = Field(default_factory=list)
    poll_interval_seconds: int = 60


class DashboardSection(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8050
    update_interval_ms: int = 2000


class AppConfig(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    broker: BrokerSection
    risk: RiskSection = Field(default_factory=RiskSection)
    strategies: StrategiesSection = Field(default_factory=StrategiesSection)
    data: DataSection = Field(default_factory=DataSection)
    ai: AISection = Field(default_factory=AISection)
    news: NewsSection = Field(default_factory=NewsSection)
    dashboard: DashboardSection = Field(default_factory=DashboardSection)
    paper: PaperSection = Field(default_factory=PaperSection)
    telegram: TelegramSection = Field(default_factory=TelegramSection)
