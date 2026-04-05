"""News/Sentiment LLM strategy.

Uses Claude API to analyze financial news and generate
trading signals based on strong sentiment.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, time

import pandas as pd

from ..ai.sentiment import SentimentAnalyzer
from ..config.schema import NewsSentimentConfig
from ..data.news.aggregator import NewsAggregator
from ..data.news.rss_reader import NewsArticle
from ..types import Candle, Signal, SignalType
from ..utils.time import IST
from .base import BaseStrategy

logger = logging.getLogger("alphaforge.strategy")


class NewsSentimentStrategy(BaseStrategy):
    """News/Sentiment — trades based on Claude-analyzed financial news."""

    def __init__(
        self,
        config: NewsSentimentConfig,
        sentiment_analyzer: SentimentAnalyzer,
        news_aggregator: NewsAggregator | None = None,
    ):
        super().__init__(name="news_sentiment", enabled=config.enabled)
        self.config = config
        self.analyzer = sentiment_analyzer
        self.aggregator = news_aggregator
        self._trades_today: dict[str, int] = defaultdict(int)
        self._pending_signals: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._watchlist = set(config.symbols)

    async def on_start(self) -> None:
        self._trades_today.clear()
        logger.info("News Sentiment: Watching %d symbols", len(self._watchlist))

    async def on_candle(self, symbol: str, candle: Candle, history: pd.DataFrame) -> Signal | None:
        """Check for pending news-based signals on each candle tick."""
        # Process pending articles from aggregator
        if self.aggregator:
            while not self.aggregator.article_queue.empty():
                try:
                    article = self.aggregator.article_queue.get_nowait()
                    signal = await self._process_article(article, candle)
                    if signal:
                        return signal
                except asyncio.QueueEmpty:
                    break

        # Check internal pending signals
        try:
            signal = self._pending_signals.get_nowait()
            return signal
        except asyncio.QueueEmpty:
            pass

        return None

    async def _process_article(self, article: NewsArticle, latest_candle: Candle) -> Signal | None:
        """Analyze a news article and generate signal if warranted."""
        ts = datetime.now(IST)

        # Only trade during market hours
        if ts.time() < time(9, 20) or ts.time() >= time(15, 0):
            return None

        # Run sentiment analysis
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self.analyzer.analyze,
            article.title,
            article.summary,
            "",
        )

        if result.confidence < self.config.sentiment_threshold:
            return None

        # Check which watched symbols are affected
        affected = [s for s in result.affected_symbols if s in self._watchlist]
        if not affected:
            # Check if headline mentions any watched symbol
            for sym in self._watchlist:
                if sym.upper() in article.title.upper():
                    affected.append(sym)

        if not affected:
            return None

        symbol = affected[0]

        # Check daily trade limit
        if self._trades_today[symbol] >= self.config.max_trades_per_day:
            return None

        # Determine signal direction
        if result.sentiment > 0.5 and result.impact in ("medium", "high"):
            signal_type = SignalType.BUY
            # Use latest candle price as reference
            price = latest_candle.close
            sl = round(price * 0.98, 2)  # 2% stop-loss for news trades
            target = round(price * 1.03, 2)  # 3% target

        elif result.sentiment < -0.5 and result.impact in ("medium", "high"):
            signal_type = SignalType.SELL
            price = latest_candle.close
            sl = round(price * 1.02, 2)
            target = round(price * 0.97, 2)

        else:
            return None

        self._trades_today[symbol] += 1

        logger.info("News signal: %s %s | Sentiment: %.2f | '%s'",
                     signal_type, symbol, result.sentiment, article.title[:60])

        return Signal(
            strategy_name=self.name,
            tradingsymbol=symbol,
            exchange="NSE",
            signal_type=signal_type,
            confidence=result.confidence,
            suggested_price=price,
            stop_loss=sl,
            target=target,
            product=self.config.product,
            metadata={
                "headline": article.title[:100],
                "sentiment": result.sentiment,
                "impact": result.impact,
                "reasoning": result.reasoning,
                "source": article.source,
            },
        )

    @property
    def required_symbols(self) -> list[str]:
        return [f"NSE:{s}" for s in self.config.symbols]

    @property
    def required_intervals(self) -> list[str]:
        return ["5minute"]
