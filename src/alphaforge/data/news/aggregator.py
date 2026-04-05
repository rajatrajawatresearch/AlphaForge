"""News aggregator — deduplicates and queues articles for sentiment analysis."""

import asyncio
import logging

from .rss_reader import NewsArticle, RSSReader

logger = logging.getLogger("alphaforge.data")


class NewsAggregator:
    """Polls RSS feeds and queues new articles for processing."""

    def __init__(self, rss_reader: RSSReader, poll_interval: int = 60):
        self.reader = rss_reader
        self.poll_interval = poll_interval
        self.article_queue: asyncio.Queue[NewsArticle] = asyncio.Queue(maxsize=500)
        self._headline_cache: set[str] = set()

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Main polling loop."""
        logger.info("News aggregator started (poll every %ds)", self.poll_interval)

        while not shutdown_event.is_set():
            try:
                articles = await asyncio.get_event_loop().run_in_executor(
                    None, self.reader.fetch_new
                )

                for article in articles:
                    # Deduplicate by headline similarity
                    normalized = article.title.lower().strip()
                    if normalized in self._headline_cache:
                        continue
                    self._headline_cache.add(normalized)

                    try:
                        self.article_queue.put_nowait(article)
                    except asyncio.QueueFull:
                        logger.warning("Article queue full, dropping: %s", article.title[:50])

            except Exception as e:
                logger.error("News aggregator error: %s", e)

            # Wait for next poll or shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self.poll_interval)
                break  # Shutdown signaled
            except asyncio.TimeoutError:
                continue  # Poll again

        logger.info("News aggregator stopped")

    def reset(self) -> None:
        self._headline_cache.clear()
        self.reader.reset()
